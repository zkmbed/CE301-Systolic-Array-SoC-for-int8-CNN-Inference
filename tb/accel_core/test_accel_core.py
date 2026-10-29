"""System test for accel_core #(N, K_max): controller + zero muxes + skew + systolic_array.

The testbench plays both DMA engines and nothing else:
  * DMA reader: drives in_valid, a_in_TOP (column k of A) and b_in_TOP (row k of B).
  * DMA writer: drives out_ready and collects res_out_TOP, one row per handshake.
  * CSR side:   drives start and K, watches busy and done.
It never looks inside accel_core: every check is on the ports, against NumPy (A @ B).

Checked on every cycle of every tile:
  - the N result rows equal A @ B exactly (rows arrive bottom row first: N-1 .. 0)
  - exactly K input handshakes and exactly N output handshakes per tile
  - exactly 2N-2 FLUSH cycles (busy, but neither in_ready nor out_valid)
  - in_ready and out_valid are never 1 together; neither is 1 when busy is 0
  - res_out_TOP holds steady while out_valid = 1 and out_ready = 0 (valid/ready rule)
  - res_out_TOP has no X or Z when out_valid = 1
  - done is 1 for exactly one cycle, the cycle after the last output handshake
  - start is followed by busy on the next cycle
Stress applied:
  - random in_valid / out_ready stalls, from none to heavy
  - junk on a_in_TOP / b_in_TOP whenever in_valid = 0 (must be ignored)
  - an "eager" reader that keeps in_valid = 1 with junk after the K real beats
    (in_ready must be 0 outside COMPUTE, so none of it may be accepted)
  - K changed to junk right after start (the controller must have latched it)
  - back-to-back tiles with 0 to 3 idle cycles between them, so any data left over
    in the skew or the accumulators from one tile would corrupt the next
  - reset in the middle of a tile at random points, then a clean tile

Inputs are driven just after a falling edge and outputs are sampled 1 ns later, so a
handshake seen in the sample is the one the next rising edge acts on.
N and K_max come from the environment and must match the build (see Makefile).
"""

import os
import random

import numpy as np
import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

N = int(os.environ.get("N", "8"))
K_MAX = int(os.environ.get("KMAX", "1024"))
K_W = K_MAX.bit_length()                 # == $clog2(K_max + 1)
SEED = int(os.environ.get("SEED", "1"))


# ----------------------------------------------------------------------------- helpers

def pack(values, width):
    """Lane i of `values` goes in bits [i*width +: width] (two's complement)."""
    word = 0
    for i, v in enumerate(values):
        word |= (int(v) & ((1 << width) - 1)) << (i * width)
    return word


def unpack(word, width):
    out = []
    for i in range(N):
        v = (word >> (i * width)) & ((1 << width) - 1)
        out.append(v - (1 << width) if v >> (width - 1) else v)
    return out


def junk_beat():
    return random.getrandbits(N * 8)


def read(sig, name):
    """Integer value of an output, failing clearly on X or Z."""
    v = sig.value
    assert v.is_resolvable, f"{name} is X or Z: {v}"
    return int(v)


async def setup(dut):
    random.seed(SEED)
    np.random.seed(SEED)
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.start.value = 0
    dut.K.value = 0
    dut.in_valid.value = 0
    dut.out_ready.value = 0
    dut.a_in_TOP.value = 0
    dut.b_in_TOP.value = 0
    await reset(dut, cycles=2)


async def reset(dut, cycles=1):
    await FallingEdge(dut.clk)
    dut.rst.value = 1
    dut.start.value = 0
    dut.in_valid.value = 0
    dut.out_ready.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.rst.value = 0
    await Timer(1, unit="ns")
    for s in ("busy", "done", "in_ready", "out_valid"):
        assert read(getattr(dut, s), s) == 0, f"{s} is 1 straight after reset"


async def idle(dut, cycles):
    for _ in range(cycles):
        await FallingEdge(dut.clk)
        dut.start.value = 0
        dut.in_valid.value = 0
        dut.out_ready.value = random.getrandbits(1)
        dut.a_in_TOP.value = junk_beat()
        dut.b_in_TOP.value = junk_beat()
        await Timer(1, unit="ns")
        for s in ("busy", "done", "in_ready", "out_valid"):
            assert read(getattr(dut, s), s) == 0, f"{s} is 1 while idle"


# ----------------------------------------------------------------------------- one tile

class Stats:
    tiles = 0
    in_stalls = 0          # cycles in COMPUTE with in_valid = 0
    out_stalls = 0         # cycles in DRAIN with out_ready = 0
    junk_offered = 0       # cycles in_valid = 1 with junk outside COMPUTE (eager reader)


async def run_tile(dut, A, B, p_in=1.0, p_out=1.0, reader="axi", abort_after=None, tag=""):
    """Run one tile through accel_core as the DMA would. Returns C (N x N) or None if aborted.

    reader = "axi":   once in_valid goes to 1 it stays 1, with the same data, until accepted
             "wild":  in_valid is re-drawn every cycle (legal for this design, harsher)
             "eager": like axi, but after the K real beats it keeps offering junk with
                      in_valid = 1; none of it may be accepted
    abort_after = n:  stop after n cycles without checking the result (for reset tests)
    """
    K = A.shape[1]
    assert B.shape[0] == K and 1 <= K <= K_MAX

    # ---- start (this cycle must be IDLE)
    await FallingEdge(dut.clk)
    dut.start.value = 1
    dut.K.value = K
    dut.in_valid.value = 0
    dut.out_ready.value = 0
    dut.a_in_TOP.value = junk_beat()
    dut.b_in_TOP.value = junk_beat()
    await Timer(1, unit="ns")
    assert read(dut.busy, "busy") == 0 and read(dut.done, "done") == 0, f"{tag}: start issued while not IDLE"

    beat = 0                  # next beat the reader will offer
    offering = False          # reader is holding in_valid = 1 (axi / eager)
    rows = []
    flush_cycles = 0
    prev_hold = None          # res_out_TOP from a cycle with out_valid = 1, out_ready = 0
    last_out_hs = False
    cycle = 0
    first = True

    while True:
        await FallingEdge(dut.clk)
        dut.start.value = 0
        dut.K.value = random.getrandbits(K_W)      # K must already be latched

        # ---- DMA reader decides this cycle's in_valid and data
        if beat < K:
            if reader == "wild":
                offering = random.random() < p_in
            elif not offering:
                offering = random.random() < p_in
            if offering:
                dut.in_valid.value = 1
                dut.a_in_TOP.value = pack(A[:, beat], 8)
                dut.b_in_TOP.value = pack(B[beat, :], 8)
            else:
                dut.in_valid.value = 0
                dut.a_in_TOP.value = junk_beat()
                dut.b_in_TOP.value = junk_beat()
        else:
            eager = reader == "eager" and random.random() < 0.8
            dut.in_valid.value = int(eager)
            dut.a_in_TOP.value = junk_beat()
            dut.b_in_TOP.value = junk_beat()

        # ---- DMA writer decides out_ready
        dut.out_ready.value = int(random.random() < p_out)

        await Timer(1, unit="ns")
        in_valid = int(dut.in_valid.value)
        out_ready = int(dut.out_ready.value)
        in_ready = read(dut.in_ready, "in_ready")
        out_valid = read(dut.out_valid, "out_valid")
        busy = read(dut.busy, "busy")
        done = read(dut.done, "done")
        where = f"{tag} K={K} cycle {cycle} (beats in {beat}, rows out {len(rows)})"

        # ---- per-cycle protocol checks
        if first:
            assert busy == 1, f"{where}: busy not 1 the cycle after start"
            first = False
        assert not (in_ready and out_valid), f"{where}: in_ready and out_valid both 1"
        if not busy:
            assert not in_ready and not out_valid, f"{where}: in_ready/out_valid while not busy"
        if beat < K:
            assert not out_valid, f"{where}: out_valid before all K beats were accepted"
        if done:
            assert last_out_hs, f"{where}: done not straight after the last output handshake"
            assert not busy, f"{where}: done and busy both 1"
        if last_out_hs:
            assert done == 1, f"{where}: done missing after the last output handshake"
        if busy and not in_ready and not out_valid:
            flush_cycles += 1
        if busy and in_ready and not in_valid:
            Stats.in_stalls += 1
        if out_valid and not out_ready:
            Stats.out_stalls += 1
        if in_valid and beat >= K:
            Stats.junk_offered += 1
            assert not in_ready, f"{where}: accepted a beat after the K real ones"

        if out_valid:
            word = read(dut.res_out_TOP, "res_out_TOP")
            if prev_hold is not None:
                assert word == prev_hold, f"{where}: res_out_TOP changed while out_ready = 0"
            prev_hold = None if out_ready else word
        else:
            prev_hold = None

        # ---- handshakes (act on the coming rising edge)
        if in_valid and in_ready:
            assert beat < K, f"{where}: more than K input handshakes"
            beat += 1
            offering = False
        last_out_hs = False
        if out_valid and out_ready:
            rows.append(unpack(read(dut.res_out_TOP, "res_out_TOP"), 32))
            assert len(rows) <= N, f"{where}: more than N output handshakes"
            last_out_hs = len(rows) == N

        cycle += 1
        if abort_after is not None and cycle >= abort_after:
            return None
        if done:
            break
        assert cycle < 200 * (K + 4 * N) + 1000, f"{where}: tile never finished"

    assert beat == K, f"{tag}: {beat} input handshakes, expected K = {K}"
    assert len(rows) == N, f"{tag}: {len(rows)} output rows, expected N = {N}"
    assert flush_cycles == 2 * N - 2, f"{tag}: {flush_cycles} FLUSH cycles, expected 2N-2 = {2 * N - 2}"
    Stats.tiles += 1
    return np.array(rows[::-1])            # rows came out bottom row first


def check(C, A, B, tag):
    ref = A.astype(np.int64) @ B.astype(np.int64)
    assert ref.min() >= -(2 ** 31) and ref.max() < 2 ** 31, "reference overflows int32 (bad test)"
    if not np.array_equal(C, ref):
        bad = np.argwhere(C != ref)
        raise AssertionError(
            f"{tag}: {len(bad)} of {N * N} results wrong, first at (row, col) {tuple(bad[0])}\n"
            f"got\n{C}\nexpected\n{ref}")


def rand_mats(K, lo=-128, hi=127):
    return (np.random.randint(lo, hi + 1, (N, K)), np.random.randint(lo, hi + 1, (K, N)))


def k_edges():
    ks = {1, 2, N - 1, N, N + 1, 2 * N - 3, 2 * N - 2, 2 * N - 1, 2 * N, K_MAX - 1, K_MAX}
    return sorted(k for k in ks if 1 <= k <= K_MAX)


# ----------------------------------------------------------------------------- tests

@cocotb.test()
async def known_tiles(dut):
    """Hand-checkable tiles, no stalls: A @ I = A, all ones gives K, and a single 1."""
    await setup(dut)
    K = N
    A = np.arange(N * K).reshape(N, K) % 256 - 128
    I = np.eye(N, dtype=int)
    check(await run_tile(dut, A, I, tag="A @ I"), A, I, "A @ I")
    ones_a, ones_b = np.ones((N, 5), int), np.ones((5, N), int)
    check(await run_tile(dut, ones_a, ones_b, tag="ones"), ones_a, ones_b, "ones")
    A1 = np.zeros((N, 1), int); B1 = np.zeros((1, N), int)
    A1[N - 1, 0] = 3; B1[0, N - 1] = -7                # only the bottom-right PE sees anything
    check(await run_tile(dut, A1, B1, tag="corner"), A1, B1, "corner")
    A1 = np.zeros((N, 1), int); B1 = np.zeros((1, N), int)
    A1[0, 0] = 5; B1[0, 0] = 9                         # only the top-left PE
    check(await run_tile(dut, A1, B1, tag="top-left"), A1, B1, "top-left")


@cocotb.test()
async def exact_latency_no_stalls(dut):
    """With no stalls, busy lasts exactly K + 3N - 2 cycles and done follows at once."""
    await setup(dut)
    for K in k_edges()[:8]:
        A, B = rand_mats(K)
        await FallingEdge(dut.clk)
        dut.start.value = 1
        dut.K.value = K
        dut.in_valid.value = 0
        dut.out_ready.value = 1
        beat, busy_cycles = 0, 0
        await FallingEdge(dut.clk)
        dut.start.value = 0
        while True:
            dut.in_valid.value = int(beat < K)
            if beat < K:
                dut.a_in_TOP.value = pack(A[:, beat], 8)
                dut.b_in_TOP.value = pack(B[beat, :], 8)
            await Timer(1, unit="ns")
            if read(dut.in_valid, "in_valid") and read(dut.in_ready, "in_ready"):
                beat += 1
            if read(dut.busy, "busy"):
                busy_cycles += 1
            elif read(dut.done, "done"):
                break
            else:
                raise AssertionError(f"K={K}: neither busy nor done mid-tile")
            await FallingEdge(dut.clk)
        assert busy_cycles == K + 3 * N - 2, f"K={K}: busy {busy_cycles} cycles, expected K+3N-2 = {K + 3 * N - 2}"
        await FallingEdge(dut.clk)


@cocotb.test()
async def extremes(dut):
    """Largest products at the largest K: checks signed multiply and the 32-bit accumulator."""
    await setup(dut)
    K = K_MAX
    for a, b in ((-128, -128), (-128, 127), (127, -128), (127, 127)):
        A = np.full((N, K), a); B = np.full((K, N), b)
        check(await run_tile(dut, A, B, tag=f"{a}x{b}"), A, B, f"{a} x {b}, K={K}")
    A = np.where(np.random.rand(N, K) < 0.5, -128, 127)
    B = np.where(np.random.rand(K, N) < 0.5, -128, 127)
    check(await run_tile(dut, A, B, p_in=0.5, p_out=0.5, tag="mixed extremes"), A, B, "mixed extremes")


@cocotb.test()
async def k_boundaries(dut):
    """Every K edge case, without stalls and then with heavy stalls."""
    await setup(dut)
    for K in k_edges():
        for p_in, p_out in ((1.0, 1.0), (0.3, 0.3)):
            A, B = rand_mats(K)
            tag = f"K={K} p_in={p_in} p_out={p_out}"
            check(await run_tile(dut, A, B, p_in, p_out, tag=tag), A, B, tag)


@cocotb.test()
async def no_leakage_between_tiles(dut):
    """A large tile, then all-zero tiles: anything left in the skew or accumulators shows up as non-zero."""
    await setup(dut)
    for K in k_edges()[:6]:
        A = np.full((N, K + 3), -128)[:, :K + 3]; B = np.full((K + 3, N), -128)
        if K + 3 <= K_MAX:
            check(await run_tile(dut, A, B, p_in=0.7, tag="big"), A, B, "big")
        Z_a, Z_b = np.zeros((N, K), int), np.zeros((K, N), int)
        check(await run_tile(dut, Z_a, Z_b, tag=f"zeros K={K}"), Z_a, Z_b, f"zeros after big tile, K={K}")


@cocotb.test()
async def junk_is_ignored(dut):
    """Junk on the data bus when in_valid = 0, and an eager reader after the last beat."""
    await setup(dut)
    for i in range(60):
        K = random.choice(k_edges() + [random.randint(1, min(K_MAX, 4 * N))])
        A, B = rand_mats(K)
        reader = random.choice(("eager", "wild"))
        tag = f"junk {i} K={K} {reader}"
        check(await run_tile(dut, A, B, random.choice((1.0, 0.5, 0.2)), random.choice((1.0, 0.5)),
                             reader=reader, tag=tag), A, B, tag)
    assert Stats.junk_offered > 0, "eager reader never offered junk (bad test)"


@cocotb.test()
async def backpressure(dut):
    """Writer mostly not ready: rows must hold steady and none may be lost or repeated."""
    await setup(dut)
    for i in range(40):
        K = random.randint(1, min(K_MAX, 3 * N))
        A, B = rand_mats(K)
        tag = f"backpressure {i} K={K}"
        check(await run_tile(dut, A, B, p_in=1.0, p_out=0.1, tag=tag), A, B, tag)
    assert Stats.out_stalls > 0, "no output stalls happened (bad test)"


@cocotb.test()
async def random_tiles(dut):
    """Many tiles, random K, random stalls, random reader behaviour, random gaps between tiles."""
    await setup(dut)
    n_tiles = int(os.environ.get("TILES", "300"))
    for i in range(n_tiles):
        K = random.choice([random.randint(1, min(K_MAX, 4 * N)), random.randint(1, min(K_MAX, 64)),
                           random.choice(k_edges())])
        if i % 9 == 0:
            A, B = rand_mats(K, -128, -127) if i % 2 else rand_mats(K, 126, 127)
        else:
            A, B = rand_mats(K)
        p_in = random.choice((1.0, 0.9, 0.5, 0.2, 0.05))
        p_out = random.choice((1.0, 0.9, 0.5, 0.2, 0.05))
        reader = random.choice(("axi", "axi", "wild", "eager"))
        tag = f"tile {i} K={K} p_in={p_in} p_out={p_out} {reader}"
        check(await run_tile(dut, A, B, p_in, p_out, reader, tag=tag), A, B, tag)
        await idle(dut, random.choice((0, 0, 1, 3)))
    dut._log.info(f"N={N} K_max={K_MAX}: {Stats.tiles} tiles so far, {Stats.in_stalls} input stalls, "
                  f"{Stats.out_stalls} output stalls, {Stats.junk_offered} junk beats refused")


@cocotb.test()
async def reset_mid_tile(dut):
    """Reset at a random point in a tile (any phase), then a clean tile must still be right."""
    await setup(dut)
    for i in range(60):
        K = random.randint(1, min(K_MAX, 3 * N))
        A, B = rand_mats(K)
        span = K + 3 * N + 2
        await run_tile(dut, A, B, p_in=0.7, p_out=0.7, abort_after=random.randint(1, span), tag=f"aborted {i}")
        await reset(dut, cycles=random.choice((1, 2)))
        K2 = random.randint(1, min(K_MAX, 3 * N))
        A2, B2 = rand_mats(K2)
        tag = f"after reset {i} K={K2}"
        check(await run_tile(dut, A2, B2, p_in=0.8, p_out=0.8, tag=tag), A2, B2, tag)
