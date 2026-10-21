"""cocotb tests for controller #(N, K_max), checked against the spec (CE301_controllerRTL_spec_v3).

Four independent kinds of check run together:
  1. A cycle-accurate Python model of the spec's state table (section 3, 4, 5, 6),
     compared with all seven outputs on every cycle.
  2. A tile scoreboard that only watches the ports: per tile, exactly K input
     handshakes (K as it was when start was accepted), exactly 2N-2 flush steps,
     exactly N output handshakes, then done for one cycle.
  3. Port invariants that must hold on every cycle whatever the state
     (e.g. en never 1 when not busy, drain == out_valid).
  4. White-box: after every clock edge, the internal state_reg, count_reg and k_reg must
     equal the model's state, count and k (this is what catches a reset that does not
     fully reset, which the ports alone cannot see). These use the RTL's internal names.
Plus hand-written exact sequences that do not use the model at all.

Inputs are driven just after a falling edge; outputs are checked 1 ns later
(they are combinational, so they must already reflect this cycle's inputs);
the model steps at the rising edge. K = 0 is illegal by the spec and is not tested.
N and K_max come from the environment and must match the build (see Makefile).
"""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge, Timer

N = int(os.environ.get("N", "8"))
K_MAX = int(os.environ.get("KMAX", "1024"))
K_W = K_MAX.bit_length()          # == $clog2(K_max + 1)

IDLE, COMPUTE, FLUSH, DRAIN, DONE = range(5)
NAMES = {IDLE: "IDLE", COMPUTE: "COMPUTE", FLUSH: "FLUSH", DRAIN: "DRAIN", DONE: "DONE"}
OUTS = ("in_ready", "out_valid", "zero_feed", "en", "drain", "busy", "done")


class SpecModel:
    """The controller as described in the spec, written independently of the RTL."""

    def __init__(self, count_bits=K_W):
        self.state, self.count, self.k = IDLE, 0, 0
        self.count_bits = count_bits

    def outputs(self, in_valid, out_ready):
        s = self.state
        o = dict.fromkeys(OUTS, 0)
        if s == COMPUTE:
            o.update(in_ready=1, busy=1, en=in_valid)
        elif s == FLUSH:
            o.update(zero_feed=1, en=1, busy=1)
        elif s == DRAIN:
            o.update(out_valid=1, zero_feed=1, drain=1, busy=1, en=out_ready)
        elif s == DONE:
            o.update(done=1)
        return o                       # IDLE and illegal codes: everything 0

    def clock(self, rst, start, K, in_valid, out_ready):
        if rst:
            self.state, self.count, self.k = IDLE, 0, 0
            return
        en = self.outputs(in_valid, out_ready)["en"]
        s, nxt = self.state, self.state
        if s == IDLE:
            nxt = COMPUTE if start else IDLE
        elif s == COMPUTE:
            if in_valid and self.count == self.k - 1:
                nxt = FLUSH
        elif s == FLUSH:
            if self.count == 2 * N - 3:
                nxt = DRAIN
        elif s == DRAIN:
            if out_ready and self.count == N - 1:
                nxt = DONE
        elif s == DONE:
            nxt = IDLE
        else:
            nxt = IDLE                 # illegal state recovers to IDLE
        if s == IDLE and nxt == COMPUTE:
            self.k = K
        if nxt != s:
            self.count = 0
        elif en:
            self.count = (self.count + 1) % (1 << self.count_bits)
        self.state = nxt


class Scoreboard:
    """Port-only checks: what each tile must look like from outside."""

    def __init__(self):
        self.clear()
        self.tiles = 0

    def clear(self):
        self.active, self.k, self.in_hs, self.flush, self.out_hs = False, None, 0, 0, 0

    def cycle(self, o, rst, start, K, in_valid, out_ready, where):
        # invariants that hold in every cycle
        assert o["drain"] == o["out_valid"], f"{where}: drain != out_valid"
        assert not (o["in_ready"] and o["out_valid"]), f"{where}: in_ready and out_valid both high"
        assert not (o["en"] and not o["busy"]), f"{where}: en high while not busy"
        assert not (o["busy"] and o["done"]), f"{where}: busy and done both high"
        assert o["zero_feed"] == (o["busy"] and not o["in_ready"]), f"{where}: zero_feed wrong"
        if o["in_ready"]:
            assert o["en"] == in_valid, f"{where}: in COMPUTE en must equal in_valid"
        if o["out_valid"]:
            assert o["en"] == out_ready, f"{where}: in DRAIN en must equal out_ready"
        if rst:
            self.clear()
            return
        # count transactions for the current tile
        if o["in_ready"] and in_valid:
            self.in_hs += 1
        if o["en"] and o["zero_feed"] and not o["drain"]:
            self.flush += 1
        if o["out_valid"] and out_ready:
            self.out_hs += 1
        if o["done"]:
            assert self.active, f"{where}: done without a tile in progress"
            assert self.in_hs == self.k, f"{where}: tile took {self.in_hs} input beats, K was {self.k}"
            assert self.flush == 2 * N - 2, f"{where}: {self.flush} flush steps, expected {2 * N - 2}"
            assert self.out_hs == N, f"{where}: {self.out_hs} output rows, expected {N}"
            self.tiles += 1
            self.clear()
        # a start is accepted only when idle (not busy, not done)
        if start and not o["busy"] and not o["done"]:
            self.active, self.k = True, K


def bit(sig, name):
    s = str(sig.value)
    assert s in ("0", "1"), f"{name} is {s} (X or Z)"
    return int(s)


class Harness:
    def __init__(self, dut):
        self.dut, self.model, self.sb, self.cyc = dut, SpecModel(len(dut.count_reg)), Scoreboard(), 0

    async def start_clock_and_reset(self):
        cocotb.start_soon(Clock(self.dut.clk, 10, unit="ns").start())
        for name in ("rst", "start", "in_valid", "out_ready", "K"):
            getattr(self.dut, name).value = 0
        self.dut.rst.value = 1
        await RisingEdge(self.dut.clk)
        await RisingEdge(self.dut.clk)
        await FallingEdge(self.dut.clk)
        self.model = SpecModel(len(self.dut.count_reg))

    async def cycle(self, rst=0, start=0, K=None, in_valid=0, out_ready=0):
        """One clock cycle: drive, check outputs against model + scoreboard, clock."""
        if K is None:
            K = random.randint(0, K_MAX)          # K is junk unless it is being latched
        d = self.dut
        d.rst.value, d.start.value, d.K.value = rst, start, K
        d.in_valid.value, d.out_ready.value = in_valid, out_ready
        await Timer(1, unit="ns")
        got = {n: bit(getattr(d, n), n) for n in OUTS}
        want = self.model.outputs(in_valid, out_ready)
        where = (f"cycle {self.cyc}, model state {NAMES.get(self.model.state, self.model.state)}, "
                 f"count {self.model.count}, k {self.model.k}, inputs rst={rst} start={start} "
                 f"K={K} in_valid={in_valid} out_ready={out_ready}")
        assert got == want, f"{where}\n  got  {got}\n  want {want}"
        self.sb.cycle(got, rst, start, K, in_valid, out_ready, where)
        await RisingEdge(d.clk)
        self.model.clock(rst, start, K, in_valid, out_ready)
        await FallingEdge(d.clk)
        inside = (int(d.state_reg.value), int(d.count_reg.value), int(d.k_reg.value))
        expect = (self.model.state, self.model.count, self.model.k)
        assert inside == expect, (f"after {where}\n  internal (state_reg, count_reg, k_reg) = {inside}, "
                                  f"model (state, count, k) = {expect}")
        self.cyc += 1
        return got

    async def run_tile(self, K, p_in=1.0, p_out=1.0, start_noise=0.0, k_noise=True, max_cycles=None):
        """Start a tile and run it to DONE; returns the number of cycles from start to done."""
        await self.cycle(start=1, K=K)
        cycles = 0
        limit = max_cycles or (K + 3 * N + 10) * 50
        while True:
            o = await self.cycle(
                start=int(random.random() < start_noise),
                K=random.randint(1, K_MAX) if k_noise else K,
                in_valid=int(random.random() < p_in),
                out_ready=int(random.random() < p_out),
            )
            cycles += 1
            if o["done"]:
                return cycles
            assert cycles < limit, f"tile with K={K} did not finish in {limit} cycles"


def rand_k():
    r = random.random()
    if r < 0.15:
        return 1
    if r < 0.20:
        return K_MAX
    if r < 0.30:
        return random.randint(1, K_MAX)
    return random.randint(1, min(K_MAX, 3 * N + 4))


@cocotb.test()
async def test_counter_can_reach_every_limit(dut):
    """The counter must be wide enough for the longest phase: COMPUTE needs K_max - 1,
    FLUSH needs 2N - 3, DRAIN needs N - 1. Reads the counter width from the design
    (internal name count_reg). Fails for builds where K_max is small next to N."""
    width = len(dut.count_reg)
    need = max(K_MAX - 1, 2 * N - 3, N - 1)
    assert (1 << width) - 1 >= need, (
        f"count_reg is {width} bits (max {(1 << width) - 1}) but a phase needs to count to {need} "
        f"(N={N}, K_max={K_MAX}); FLUSH would end early or never")


@cocotb.test()
async def test_reset_and_idle(dut):
    """After reset every output is 0 and stays 0 in IDLE whatever in_valid / out_ready do.
    Holding reset blocks start."""
    h = Harness(dut)
    await h.start_clock_and_reset()
    for _ in range(20):
        await h.cycle(rst=1, start=1, K=min(5, K_MAX), in_valid=1, out_ready=1)
    for _ in range(50):
        await h.cycle(in_valid=random.randint(0, 1), out_ready=random.randint(0, 1))


@cocotb.test()
async def test_exact_sequence(dut):
    """Hand-written expected outputs (not the model): K COMPUTE cycles, 2N-2 FLUSH,
    N DRAIN, 1 DONE, then IDLE. Several K, no stalls."""
    h = Harness(dut)
    await h.start_clock_and_reset()
    C = dict(in_ready=1, out_valid=0, zero_feed=0, en=1, drain=0, busy=1, done=0)
    F = dict(in_ready=0, out_valid=0, zero_feed=1, en=1, drain=0, busy=1, done=0)
    D = dict(in_ready=0, out_valid=1, zero_feed=1, en=1, drain=1, busy=1, done=0)
    E = dict(in_ready=0, out_valid=0, zero_feed=0, en=0, drain=0, busy=0, done=1)
    I = dict.fromkeys(OUTS, 0)
    for K in sorted(k for k in {1, 2, 3, N, 2 * N + 1, 37, K_MAX} if k <= K_MAX):
        expected = [C] * K + [F] * (2 * N - 2) + [D] * N + [E] + [I] * 2
        got = await h.cycle(start=1, K=K)
        assert got == I, f"K={K}: outputs not idle in the start cycle: {got}"
        for i, want in enumerate(expected):
            got = await h.cycle(K=random.randint(1, K_MAX), in_valid=1, out_ready=1)
            assert got == want, f"K={K}, cycle {i} after start: got {got}, want {want}"


@cocotb.test()
async def test_tile_length_no_stalls(dut):
    """Without stalls, done appears exactly K + (2N-2) + N + 1 cycles after the start cycle."""
    h = Harness(dut)
    await h.start_clock_and_reset()
    ks = sorted({1, 2, 3, 4, 7, 8, 9, N - 1, N, N + 1, 2 * N - 2, 2 * N, 100, K_MAX - 1, K_MAX})
    for K in [k for k in ks if 1 <= k <= K_MAX]:
        cycles = await h.run_tile(K)
        assert cycles == K + 3 * N - 1, f"K={K}: done after {cycles} cycles, expected {K + 3 * N - 1}"
        await h.cycle()


@cocotb.test()
async def test_random_tiles_with_stalls(dut):
    """300 tiles, random K (1, K_max and in between), random gaps on in_valid and
    backpressure on out_ready (different rates per tile), K changing every cycle
    after start, random start pulses while busy (must be ignored), random idle gaps."""
    random.seed(1000 + N)
    h = Harness(dut)
    await h.start_clock_and_reset()
    for _ in range(300):
        await h.run_tile(rand_k(), p_in=random.choice([1.0, 0.8, 0.5, 0.2]),
                         p_out=random.choice([1.0, 0.8, 0.5, 0.2]), start_noise=0.3)
        for _ in range(random.choice([0, 0, 1, 3])):
            await h.cycle(in_valid=random.randint(0, 1), out_ready=random.randint(0, 1))
    assert h.sb.tiles == 300


@cocotb.test()
async def test_k_latched_at_start(dut):
    """K changes every cycle after start (including to 0 and K_max): the tile must still
    take exactly the K that was there when start was accepted."""
    random.seed(2000 + N)
    h = Harness(dut)
    await h.start_clock_and_reset()
    for _ in range(100):
        K = rand_k()
        await h.cycle(start=1, K=K)
        while True:
            o = await h.cycle(K=random.choice([0, 1, K_MAX, random.randint(0, K_MAX)]),
                              in_valid=int(random.random() < 0.7), out_ready=int(random.random() < 0.7))
            if o["done"]:
                break
    assert h.sb.tiles == 100


@cocotb.test()
async def test_start_held_high(dut):
    """start held at 1 forever: tiles run back to back with exactly one IDLE cycle
    between DONE and the next COMPUTE; nothing restarts a tile early."""
    random.seed(3000 + N)
    h = Harness(dut)
    await h.start_clock_and_reset()
    K = min(3, K_MAX)
    seen_done = 0
    gap = None
    for _ in range(40 * (K + 3 * N + 2)):
        o = await h.cycle(start=1, K=K, in_valid=1, out_ready=1)
        if o["done"]:
            seen_done += 1
            gap = 0
        elif gap is not None:
            gap += 1
            if o["busy"]:
                assert gap == 2, f"next tile started {gap} cycles after done, expected 2 (one IDLE cycle)"
                gap = None
    assert seen_done >= 30


@cocotb.test()
async def test_stalls_at_the_edges(dut):
    """in_valid low exactly on the last beat; out_ready low on the first and on the last
    drain row; long stalls in the middle. Everything checked by the model each cycle."""
    random.seed(4000 + N)
    h = Harness(dut)
    await h.start_clock_and_reset()
    for K in [1, 2, 5]:
        if K > K_MAX:
            continue
        await h.cycle(start=1, K=K)
        for _ in range(K - 1):                      # all beats but the last
            await h.cycle(in_valid=1)
        for _ in range(5):                          # stall right before the last beat
            await h.cycle(in_valid=0, out_ready=1)
        await h.cycle(in_valid=1)                   # last beat
        for _ in range(2 * N - 2):                  # flush ignores in_valid and out_ready
            await h.cycle(in_valid=random.randint(0, 1), out_ready=0)
        for _ in range(4):                          # out_ready low on the first row
            await h.cycle(out_ready=0)
        for _ in range(N - 1):
            await h.cycle(out_ready=1)
        for _ in range(4):                          # out_ready low on the last row
            await h.cycle(out_ready=0)
        o = await h.cycle(out_ready=1)
        assert not o["done"]
        o = await h.cycle()
        assert o["done"], "done should follow the last row's handshake"
    assert h.sb.tiles == len([k for k in (1, 2, 5) if k <= K_MAX])


@cocotb.test()
async def test_reset_in_every_state(dut):
    """Reset at every cycle position of a tile (every state, every count value),
    then a normal tile must run correctly."""
    random.seed(5000 + N)
    h = Harness(dut)
    await h.start_clock_and_reset()
    K = min(K_MAX, 4)
    length = K + 3 * N + 1
    for at in range(length + 1):
        await h.cycle(start=1, K=K)
        for _ in range(at):
            await h.cycle(in_valid=1, out_ready=1)
        await h.cycle(rst=1, start=random.randint(0, 1), in_valid=1, out_ready=1)
        o = await h.cycle(in_valid=1, out_ready=1)
        assert not any(o.values()), f"outputs not all 0 after reset at position {at}: {o}"
        await h.run_tile(rand_k(), p_in=0.7, p_out=0.7)


@cocotb.test()
async def test_illegal_states_recover(dut):
    """Force the state register to the unused codes 5, 6, 7: all outputs 0, and the next
    edge goes to IDLE; a normal tile then works. Uses the internal name state_reg."""
    random.seed(6000 + N)
    h = Harness(dut)
    await h.start_clock_and_reset()
    for code in (5, 6, 7):
        dut.state_reg.value = code
        h.model.state = code
        await Timer(1, unit="ns")
        o = await h.cycle(start=1, K=min(3, K_MAX), in_valid=1, out_ready=1)
        assert not any(o.values()), f"state {code}: outputs not all 0: {o}"
        assert h.model.state == IDLE
        o = await h.cycle()
        assert not any(o.values()), f"after state {code}: not IDLE: {o}"
        await h.run_tile(rand_k(), p_in=0.7, p_out=0.7)


@cocotb.test()
async def test_random_everything(dut):
    """30,000 cycles of random inputs: start, K (never 0), in_valid, out_ready at random,
    and reset about once in 200 cycles. Model + scoreboard + invariants every cycle."""
    random.seed(7000 + N)
    h = Harness(dut)
    await h.start_clock_and_reset()
    for _ in range(30000):
        await h.cycle(rst=int(random.random() < 0.005), start=int(random.random() < 0.3),
                      K=rand_k(), in_valid=int(random.random() < 0.6), out_ready=int(random.random() < 0.6))
    assert h.sb.tiles > 50, f"only {h.sb.tiles} tiles completed"
