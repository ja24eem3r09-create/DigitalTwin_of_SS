"""
=============================================================================
BLOCKCHAIN-BASED PEER-TO-PEER (P2P) ENERGY TRADING FRAMEWORK
WITH FALSE DATA INJECTION ATTACK (FDIA) DETECTION & BLOCKING
=============================================================================
A real-time trading simulation for multiple microgrids with:
- Electric Vehicles (EVs) and Battery Energy Storage Systems (BESS)
- Three-layer market with CORRECTED priority order:
    SURPLUS: P2P Buyers FIRST → Battery SECOND → Main Grid THIRD
    DEFICIT: Own BESS FIRST → P2P Neighbors SECOND → Main Grid THIRD
- Permissioned blockchain with smart contract settlement
- Full seller & buyer microgrid names in every trade log
- Blockchain blocks clearly labeled with their contained trades

NEW — CYBER SECURITY MODULE:
- FDIA (False Data Injection Attack) simulation: any participant can
  inject a falsified bid/ask quantity or price at a random instant
- Statistical anomaly detector: Z-score + bounds check flags suspicious
  orders in real time
- Smart-contract-level FDIA validator: cross-checks declared net energy
  against physical generation/load limits
- Repeat-offender blocking: a participant confirmed guilty of FDIA is
  BLACKLISTED from the auction and blockchain for the rest of the day
- Full attack/detection/block event log printed at the end

References:
[1] Veerasamy et al. (2024) - Blockchain-enabled double auction P2P trading
[2] Umar et al. (2024) - Decentralized energy trading in microgrids
[3] Zhou et al. (2021) - Iterative double auction + blockchain in microgrids
[4] Boumaiza (2024) - Blockchain P2P platform for prosumers
[5] Liang et al. (2017) - Review of FDIA on smart grid power systems
"""

import hashlib
import json
import time
import random
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

# =============================================================================
# COLOR PALETTE
# =============================================================================
PRIMARY   = '#065A82'
SECONDARY = '#1C7293'
ACCENT    = '#02C39A'
DARK      = '#0B132B'
LIGHT     = '#E8F4F8'
ORANGE    = '#F4845F'
YELLOW    = '#F0C808'
GRAY      = '#6B7280'
RED       = '#EF4444'
PURPLE    = '#8B5CF6'
CRIMSON   = '#DC143C'   # used for FDIA alerts

MG_COLORS = {
    'MG1': '#065A82',
    'MG2': '#02C39A',
    'MG3': '#F0C808',
    'MG4': '#F4845F',
    'MG5': '#8B5CF6',
}

# =============================================================================
# 1. DATA MODELS
# =============================================================================
@dataclass
class SolarPanel:
    capacity_kw: float
    efficiency: float = 0.85

    def generate(self, hour: int, weather_factor: float = 1.0) -> float:
        if 6 <= hour <= 18:
            irradiance = np.sin(np.pi * (hour - 6) / 12)
            return self.capacity_kw * self.efficiency * irradiance * weather_factor
        return 0.0


@dataclass
class BatteryStorage:
    capacity_kwh: float
    soc: float = 0.5
    charge_rate_kw: float = 5.0
    discharge_rate_kw: float = 5.0
    efficiency: float = 0.95

    @property
    def energy_stored(self) -> float:
        return self.capacity_kwh * self.soc

    def charge(self, energy_kwh: float) -> float:
        available_capacity = self.capacity_kwh * (1.0 - self.soc)
        actual = min(energy_kwh * self.efficiency, available_capacity, self.charge_rate_kw)
        self.soc += actual / self.capacity_kwh
        return actual

    def discharge(self, energy_kwh: float) -> float:
        available_energy = self.capacity_kwh * (self.soc - 0.1)
        actual = min(energy_kwh, max(available_energy, 0), self.discharge_rate_kw)
        if actual > 0:
            self.soc -= actual / self.capacity_kwh
        return max(actual, 0.0)


@dataclass
class ElectricVehicle:
    battery_kwh: float = 60.0
    soc: float = 0.7
    connected: bool = True
    v2g_willing: float = 0.2

    def available_energy(self) -> float:
        if self.connected and self.soc > 0.3:
            return self.battery_kwh * self.v2g_willing * (self.soc - 0.3)
        return 0.0

    def discharge(self, energy_kwh: float) -> float:
        actual = min(energy_kwh, self.available_energy())
        if actual > 0:
            self.soc -= actual / self.battery_kwh
        return actual


@dataclass
class Microgrid:
    id: str
    name: str
    solar: SolarPanel
    battery: BatteryStorage
    evs: List[ElectricVehicle]
    base_load_kw: float
    load_variability: float = 0.2

    def get_load(self, hour: int) -> float:
        if 7 <= hour <= 9:
            peak_factor = 1.4
        elif 18 <= hour <= 21:
            peak_factor = 1.6
        elif 0 <= hour <= 5:
            peak_factor = 0.5
        else:
            peak_factor = 1.0
        noise = random.uniform(-self.load_variability, self.load_variability)
        return self.base_load_kw * peak_factor * (1 + noise)

    def discharge_own_bess(self, deficit_kwh: float) -> float:
        """DEFICIT PRIORITY 1: Draw from own BESS first."""
        from_bess = self.battery.discharge(deficit_kwh)
        remaining = deficit_kwh - from_bess
        for ev in self.evs:
            if remaining <= 0.01:
                break
            from_ev = ev.discharge(remaining)
            remaining -= from_ev
        return deficit_kwh - max(remaining, 0)

    def charge_own_bess(self, surplus_kwh: float) -> float:
        """SURPLUS PRIORITY 2 (fallback): Charge own BESS if no buyers."""
        return self.battery.charge(surplus_kwh)


# =============================================================================
# 2. ORDER BOOK AND DOUBLE AUCTION
# =============================================================================
@dataclass
class Order:
    microgrid_id: str
    microgrid_name: str
    order_type: str          # 'bid' or 'ask'
    quantity_kwh: float
    price_per_kwh: float
    timestamp: float = field(default_factory=time.time)
    is_fdia: bool = False    # internal flag — set by FDIA engine


@dataclass
class Trade:
    buyer_id: str
    buyer_name: str
    seller_id: str
    seller_name: str
    quantity_kwh: float
    price_per_kwh: float
    block_number: Optional[int] = None
    timestamp: float = field(default_factory=time.time)


class DoubleAuction:
    """
    Periodic double auction. Clearing price = midpoint of matched bid/ask.
    Orders from blacklisted nodes are silently dropped.
    """
    def __init__(self):
        self.bids: List[Order] = []
        self.asks: List[Order] = []
        self.trades: List[Trade] = []
        self.clearing_price: float = 0.0

    def submit_order(self, order: Order, blacklist: set) -> bool:
        """Returns False if order rejected (blacklisted or FDIA flagged)."""
        if order.microgrid_id in blacklist:
            return False
        if order.order_type == 'bid':
            self.bids.append(order)
        else:
            self.asks.append(order)
        return True

    def clear_market(self) -> List[Trade]:
        self.bids.sort(key=lambda o: o.price_per_kwh, reverse=True)
        self.asks.sort(key=lambda o: o.price_per_kwh)
        trades = []
        bid_idx, ask_idx = 0, 0
        while bid_idx < len(self.bids) and ask_idx < len(self.asks):
            bid = self.bids[bid_idx]
            ask = self.asks[ask_idx]
            if bid.price_per_kwh >= ask.price_per_kwh:
                clearing_price = (bid.price_per_kwh + ask.price_per_kwh) / 2
                trade_qty = min(bid.quantity_kwh, ask.quantity_kwh)
                trade = Trade(
                    buyer_id=bid.microgrid_id,
                    buyer_name=bid.microgrid_name,
                    seller_id=ask.microgrid_id,
                    seller_name=ask.microgrid_name,
                    quantity_kwh=round(trade_qty, 3),
                    price_per_kwh=round(clearing_price, 4),
                )
                trades.append(trade)
                self.clearing_price = clearing_price
                bid.quantity_kwh -= trade_qty
                ask.quantity_kwh -= trade_qty
                if bid.quantity_kwh <= 0.001:
                    bid_idx += 1
                if ask.quantity_kwh <= 0.001:
                    ask_idx += 1
            else:
                break
        self.trades = trades
        self.bids.clear()
        self.asks.clear()
        return trades


# =============================================================================
# 3. FDIA (FALSE DATA INJECTION ATTACK) ENGINE
# =============================================================================
class FDIAEngine:
    """
    Simulates and detects False Data Injection Attacks (FDIA).

    Attack model:
      A malicious participant inflates its declared surplus (ask quantity)
      or deflates its declared deficit (bid quantity) to manipulate clearing
      prices or gain unfair energy access. The injected value deviates from
      the physically plausible range.

    Detection:
      1. Bounds check  — declared quantity > physical generation capacity
      2. Z-score check — order deviates > ZSCORE_THRESHOLD σ from the
                         rolling mean of that microgrid's historical orders
      3. Price anomaly — price outside [PRICE_MIN, PRICE_MAX] corridor

    Penalty:
      - First offence  → WARNING + order dropped
      - Second offence → BLACKLIST (node banned for rest of simulation)
    """

    ZSCORE_THRESHOLD = 2.5
    PRICE_MIN        = 0.07
    PRICE_MAX        = 0.26
    MAX_PLAUSIBLE_QTY = 40.0   # kWh — physical upper bound per hour

    def __init__(self):
        # rolling history of (quantity, price) per microgrid
        self.history: Dict[str, List[Tuple[float, float]]] = {}
        # offence counter
        self.offences: Dict[str, int] = {}
        # full event log
        self.event_log: List[Dict] = []

    def _update_history(self, mg_id: str, qty: float, price: float):
        if mg_id not in self.history:
            self.history[mg_id] = []
        self.history[mg_id].append((qty, price))
        # keep last 12 observations
        self.history[mg_id] = self.history[mg_id][-12:]

    def _zscore(self, mg_id: str, qty: float) -> float:
        hist = self.history.get(mg_id, [])
        if len(hist) < 3:
            return 0.0
        qtys = [h[0] for h in hist]
        mu, sigma = np.mean(qtys), np.std(qtys)
        if sigma < 1e-6:
            return 0.0
        return abs(qty - mu) / sigma

    def inject_attack(self, order: Order, mg: Microgrid, hour: int) -> Order:
        """
        Mutate an order to simulate an FDIA injection.
        The attacker inflates quantity by 200-400 % or moves price outside
        the fair corridor.
        """
        attack_type = random.choice(['qty_inflation', 'price_manipulation'])
        original_qty   = order.quantity_kwh
        original_price = order.price_per_kwh

        if attack_type == 'qty_inflation':
            multiplier = random.uniform(2.0, 4.0)
            order.quantity_kwh = round(original_qty * multiplier, 3)
        else:  # price_manipulation
            if order.order_type == 'ask':
                order.price_per_kwh = round(random.uniform(0.35, 0.50), 4)  # dump at high price
            else:
                order.price_per_kwh = round(random.uniform(0.001, 0.04), 4) # bid near zero

        order.is_fdia = True
        print(f"\n  ⚠  [FDIA INJECTED] Hour {hour:02d} | {order.microgrid_id} ({order.microgrid_name})")
        print(f"     Attack type : {attack_type.replace('_', ' ').upper()}")
        print(f"     Original    : qty={original_qty:.3f} kWh  price=${original_price:.4f}/kWh")
        print(f"     Injected    : qty={order.quantity_kwh:.3f} kWh  price=${order.price_per_kwh:.4f}/kWh")
        return order

    def detect(self, order: Order, mg: Microgrid, hour: int,
               blacklist: set) -> Tuple[bool, str]:
        """
        Returns (is_attack_detected, reason_string).
        Updates history BEFORE checking so that the injected value is
        compared against the prior clean distribution.
        """
        mg_id = order.microgrid_id
        qty   = order.quantity_kwh
        price = order.price_per_kwh

        reasons = []

        # --- Check 1: Physical plausibility ---
        max_possible = mg.solar.capacity_kw * mg.solar.efficiency + \
                       mg.battery.discharge_rate_kw + \
                       sum(ev.battery_kwh * ev.v2g_willing for ev in mg.evs)
        if qty > max_possible * 1.05:
            reasons.append(
                f"qty {qty:.2f} kWh exceeds physical max {max_possible:.2f} kWh"
            )

        # --- Check 2: Z-score anomaly ---
        z = self._zscore(mg_id, qty)
        if z > self.ZSCORE_THRESHOLD:
            reasons.append(f"Z-score={z:.2f} > threshold {self.ZSCORE_THRESHOLD}")

        # --- Check 3: Price corridor ---
        if price < self.PRICE_MIN or price > self.PRICE_MAX:
            reasons.append(
                f"price ${price:.4f} outside corridor "
                f"[${self.PRICE_MIN}, ${self.PRICE_MAX}]"
            )

        self._update_history(mg_id, qty, price)

        detected = len(reasons) > 0
        reason_str = " | ".join(reasons) if reasons else "OK"
        return detected, reason_str

    def handle_offence(self, mg_id: str, mg_name: str, hour: int,
                       reason: str, blacklist: set):
        """Record offence, warn or blacklist."""
        self.offences[mg_id] = self.offences.get(mg_id, 0) + 1
        count = self.offences[mg_id]

        event = {
            'hour': hour,
            'mg_id': mg_id,
            'mg_name': mg_name,
            'offence_count': count,
            'reason': reason,
            'action': 'BLACKLISTED' if count >= 2 else 'WARNING',
        }
        self.event_log.append(event)

        if count >= 2:
            blacklist.add(mg_id)
            print(f"  🚫 [BLACKLISTED] {mg_id} ({mg_name}) — "
                  f"offence #{count}. PERMANENTLY EXCLUDED from auction & blockchain.")
        else:
            print(f"  ⛔ [FDIA DETECTED] Hour {hour:02d} | {mg_id} ({mg_name})")
            print(f"     Reason     : {reason}")
            print(f"     Offence #  : {count} — ORDER DROPPED (next = BLACKLIST)")

    def print_security_report(self):
        """Print the full FDIA security report at end of simulation."""
        sep = "=" * 70
        print(f"\n{sep}")
        print("  CYBER SECURITY REPORT — FDIA DETECTION LOG")
        print(sep)
        if not self.event_log:
            print("  No FDIA events detected during simulation.")
        else:
            for ev in self.event_log:
                tag = "🚫 BLACKLIST" if ev['action'] == 'BLACKLISTED' else "⛔ WARNING  "
                print(f"  {tag} | Hour {ev['hour']:02d} | {ev['mg_id']} ({ev['mg_name']})")
                print(f"           Offence #{ev['offence_count']} | Reason: {ev['reason']}")
        print(f"\n  Total FDIA events detected : {len(self.event_log)}")
        blacklisted = [e['mg_id'] for e in self.event_log if e['action'] == 'BLACKLISTED']
        if blacklisted:
            unique_bl = list(dict.fromkeys(blacklisted))
            print(f"  Blacklisted participants   : {', '.join(unique_bl)}")
        print(sep)


# =============================================================================
# 4. PERMISSIONED BLOCKCHAIN
# =============================================================================
@dataclass
class Block:
    index: int
    timestamp: str
    transactions: List[Dict]
    previous_hash: str
    validator: str = ""
    nonce: int = 0
    hash: str = ""

    def compute_hash(self) -> str:
        block_string = json.dumps({
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "validator": self.validator,
        }, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()


class PermissionedBlockchain:
    def __init__(self, difficulty: int = 2):
        self.chain: List[Block] = []
        self.difficulty = difficulty
        self.authorized_nodes: set = set()
        self.pending_transactions: List[Dict] = []
        self.block_log: List[str] = []
        self._create_genesis_block()

    def _create_genesis_block(self):
        genesis = Block(0, str(datetime.now()), [], "0" * 64, validator="GENESIS")
        genesis.hash = genesis.compute_hash()
        self.chain.append(genesis)
        self.block_log.append(
            "╔══════════════════════════════════════════╗\n"
            "║  BLOCK #0 — GENESIS BLOCK               ║\n"
            "╚══════════════════════════════════════════╝\n"
            f" Hash: {genesis.hash[:20]}...\n"
        )

    def register_node(self, node_id: str):
        self.authorized_nodes.add(node_id)

    def revoke_node(self, node_id: str):
        """Remove a blacklisted participant from the authorized set."""
        self.authorized_nodes.discard(node_id)

    def smart_contract_validate(self, trade: Dict) -> bool:
        if trade['quantity_kwh'] <= 0:
            return False
        if trade['price_per_kwh'] <= 0 or trade['price_per_kwh'] > 0.50:
            return False
        if trade['buyer_id'] not in self.authorized_nodes:
            return False
        if trade['seller_id'] not in self.authorized_nodes:
            return False
        return True

    def add_trade(self, trade: Trade) -> bool:
        trade_dict = {
            'trade_id':      f"TXN-{len(self.pending_transactions)+1:04d}",
            'buyer_id':      trade.buyer_id,
            'buyer_name':    trade.buyer_name,
            'seller_id':     trade.seller_id,
            'seller_name':   trade.seller_name,
            'quantity_kwh':  trade.quantity_kwh,
            'price_per_kwh': trade.price_per_kwh,
            'total_cost_usd': round(trade.quantity_kwh * trade.price_per_kwh, 4),
            'timestamp':     trade.timestamp,
            'status':        'pending',
        }
        if self.smart_contract_validate(trade_dict):
            trade_dict['status'] = 'validated'
            self.pending_transactions.append(trade_dict)
            return True
        return False

    def mine_block(self, validator_id: str, hour: int) -> Optional[Block]:
        if validator_id not in self.authorized_nodes:
            return None
        if not self.pending_transactions:
            return None
        for tx in self.pending_transactions:
            tx['status'] = 'settled'
        new_block = Block(
            index=len(self.chain),
            timestamp=str(datetime.now()),
            transactions=self.pending_transactions.copy(),
            previous_hash=self.chain[-1].hash,
            validator=validator_id,
        )
        while not new_block.compute_hash().startswith("0" * self.difficulty):
            new_block.nonce += 1
        new_block.hash = new_block.compute_hash()
        for tx in new_block.transactions:
            tx['block_number'] = new_block.index
        self.chain.append(new_block)
        self.pending_transactions.clear()

        n        = new_block.index
        tx_count = len(new_block.transactions)
        lines = [
            f"╔══════════════════════════════════════════════════════════╗",
            f"║  BLOCK #{n:<4d} │ Hour {hour:02d} │ Validator: {validator_id:<5s}       ║",
            f"╠══════════════════════════════════════════════════════════╣",
            f"║  Transactions: {tx_count:<3d}  │  Nonce: {new_block.nonce:<6d}             ║",
            f"║  Prev Hash : {new_block.previous_hash[:30]}... ║",
            f"║  This Hash : {new_block.hash[:30]}... ║",
            f"╠══════════════════════════════════════════════════════════╣",
        ]
        for i, tx in enumerate(new_block.transactions, 1):
            lines.append(
                f"║  [{i:02d}] {tx['trade_id']}  "
                f"SELLER: {tx['seller_id']} ({tx['seller_name']:<22s}) ║"
            )
            lines.append(
                f"║        ───────►  "
                f"BUYER : {tx['buyer_id']} ({tx['buyer_name']:<22s}) ║"
            )
            lines.append(
                f"║        {tx['quantity_kwh']:.3f} kWh @ ${tx['price_per_kwh']:.4f}/kWh"
                f" = ${tx['total_cost_usd']:.4f}  Status: {tx['status']:<9s} ║"
            )
            if i < tx_count:
                lines.append(
                    f"║  ─────────────────────────────────────────────────────── ║"
                )
        lines.append(
            f"╚══════════════════════════════════════════════════════════╝"
        )
        self.block_log.append("\n".join(lines))
        return new_block

    def get_ledger_summary(self) -> Dict:
        total_trades  = sum(len(b.transactions) for b in self.chain)
        total_energy  = sum(tx['quantity_kwh']  for b in self.chain for tx in b.transactions)
        total_value   = sum(tx['total_cost_usd'] for b in self.chain for tx in b.transactions)
        return {
            'blocks':           len(self.chain),
            'total_trades':     total_trades,
            'total_energy_kwh': round(total_energy, 2),
            'total_value_usd':  round(total_value, 2),
        }

    def print_chain(self):
        print("\n" + "=" * 65)
        print("  BLOCKCHAIN LEDGER — ALL BLOCKS")
        print("=" * 65)
        for summary in self.block_log:
            print(summary)


# =============================================================================
# 5. MAIN GRID INTERFACE
# =============================================================================
class MainGrid:
    def __init__(self, buy_price: float = 0.25, sell_price: float = 0.08):
        self.buy_price    = buy_price
        self.sell_price   = sell_price
        self.total_imported = 0.0
        self.total_exported = 0.0
        self.total_cost   = 0.0

    def exchange(self, net_energy: float) -> float:
        if net_energy > 0:
            revenue = net_energy * self.sell_price
            self.total_exported += net_energy
            self.total_cost -= revenue
            return -revenue
        elif net_energy < 0:
            cost = abs(net_energy) * self.buy_price
            self.total_imported += abs(net_energy)
            self.total_cost += cost
            return cost
        return 0.0


# =============================================================================
# 6. SIMULATION ENGINE — CORRECTED PRIORITY ORDER + FDIA INTEGRATION
#
# SURPLUS microgrid:
#   Priority 1 → Submit ASK to P2P auction (find buyers first)
#   Priority 2 → Charge own BESS with what was NOT matched
#   Priority 3 → Export residual to Main Grid
#
# DEFICIT microgrid:
#   Priority 1 → Discharge own BESS (+ own EVs via V2G)
#   Priority 2 → Submit BID to P2P auction (buy from neighbors)
#   Priority 3 → Import residual from Main Grid
#
# FDIA layer (new):
#   - At each hour, 0-2 random participants MAY launch an FDIA
#   - Each order is screened by FDIAEngine.detect() before auction submission
#   - Detected offenders accumulate warnings; 2nd offence → BLACKLIST
# =============================================================================
class EnergyTradingSimulation:
    # probability that any single microgrid launches an FDIA this hour
    FDIA_PROB_PER_MG_PER_HOUR = 0.08   # ~8 % chance per MG per hour

    def __init__(self):
        self.microgrids = self._create_microgrids()
        self.auction    = DoubleAuction()
        self.blockchain = PermissionedBlockchain(difficulty=2)
        self.main_grid  = MainGrid()
        self.fdia       = FDIAEngine()
        self.blacklist: set = set()       # mg_ids permanently banned

        for mg in self.microgrids:
            self.blockchain.register_node(mg.id)

        # ---------- DATA TRACKING ----------
        self.hourly_data            = []
        self.solar_per_hour         = {mg.id: [] for mg in self.microgrids}
        self.load_per_hour          = {mg.id: [] for mg in self.microgrids}
        self.battery_soc_per_hour   = {mg.id: [] for mg in self.microgrids}
        self.trades_per_hour        = []
        self.clearing_prices        = []
        self.grid_import_per_hour   = []
        self.grid_export_per_hour   = []
        self.p2p_energy_per_hour    = []
        self.all_trades_log         = []
        # FDIA tracking per hour (for chart)
        self.fdia_attacks_per_hour  = []   # count of attacks attempted
        self.fdia_blocked_per_hour  = []   # count successfully blocked

    def _create_microgrids(self) -> List[Microgrid]:
        return [
            Microgrid("MG1", "Residential Community",
                      SolarPanel(15.0), BatteryStorage(20.0, soc=0.6),
                      [ElectricVehicle(60, 0.8), ElectricVehicle(40, 0.6)],
                      base_load_kw=8.0),
            Microgrid("MG2", "Commercial District",
                      SolarPanel(25.0), BatteryStorage(40.0, soc=0.4),
                      [ElectricVehicle(75, 0.9)],
                      base_load_kw=18.0),
            Microgrid("MG3", "University Campus",
                      SolarPanel(30.0), BatteryStorage(50.0, soc=0.5),
                      [ElectricVehicle(60, 0.7), ElectricVehicle(60, 0.7),
                       ElectricVehicle(50, 0.5)],
                      base_load_kw=22.0),
            Microgrid("MG4", "Industrial Park",
                      SolarPanel(10.0), BatteryStorage(15.0, soc=0.3),
                      [ElectricVehicle(80, 0.4)],
                      base_load_kw=25.0),
            Microgrid("MG5", "Smart Village",
                      SolarPanel(20.0), BatteryStorage(30.0, soc=0.7),
                      [ElectricVehicle(50, 0.6), ElectricVehicle(45, 0.8)],
                      base_load_kw=6.0),
        ]

    def _p2p_ask_price(self, mg: Microgrid) -> float:
        urgency = mg.battery.soc
        return max(0.08, 0.15 - 0.03 * urgency + random.uniform(-0.01, 0.01))

    def _p2p_bid_price(self, mg: Microgrid) -> float:
        urgency = 1.0 - mg.battery.soc
        return min(0.24, 0.15 + 0.05 * urgency + random.uniform(-0.01, 0.01))

    # ------------------------------------------------------------------
    def run_hour(self, hour: int, weather: float = 1.0) -> Dict:
        hour_record = {'hour': hour, 'microgrids': {}, 'trades': [], 'grid_exchanges': {}}

        # ── Compute raw generation & load ──────────────────────────────
        raw_gen  = {}
        raw_load = {}
        for mg in self.microgrids:
            g = mg.solar.generate(hour, weather)
            l = mg.get_load(hour)
            raw_gen[mg.id]  = g
            raw_load[mg.id] = l
            self.solar_per_hour[mg.id].append(g)
            self.load_per_hour[mg.id].append(l)

        # ── DEFICIT PRIORITY 1: Discharge own BESS ─────────────────────
        net_after_bess = {}
        for mg in self.microgrids:
            net = raw_gen[mg.id] - raw_load[mg.id]
            if net < -0.01:
                from_bess = mg.discharge_own_bess(abs(net))
                net = net + from_bess
            net_after_bess[mg.id] = net

        # ── FDIA LAYER + SURPLUS/DEFICIT P2P Orders ────────────────────
        hour_attacks = 0
        hour_blocked = 0

        for mg in self.microgrids:
            if mg.id in self.blacklist:
                continue   # blacklisted — skip entirely

            net = net_after_bess[mg.id]
            if abs(net) <= 0.01:
                continue   # balanced — no order needed

            order_type = 'ask' if net > 0.01 else 'bid'
            price      = self._p2p_ask_price(mg) if order_type == 'ask' else self._p2p_bid_price(mg)
            order      = Order(mg.id, mg.name, order_type, abs(net), price)

            # ── Decide whether this MG launches an FDIA this instant ──
            is_attacker = (random.random() < self.FDIA_PROB_PER_MG_PER_HOUR)
            if is_attacker:
                order = self.fdia.inject_attack(order, mg, hour)
                hour_attacks += 1

            # ── Detection ─────────────────────────────────────────────
            detected, reason = self.fdia.detect(order, mg, hour, self.blacklist)
            if detected:
                self.fdia.handle_offence(mg.id, mg.name, hour, reason, self.blacklist)
                hour_blocked += 1
                # Revoke blockchain access if now blacklisted
                if mg.id in self.blacklist:
                    self.blockchain.revoke_node(mg.id)
                continue  # drop the malicious order

            # ── Submit clean order ─────────────────────────────────────
            self.auction.submit_order(order, self.blacklist)

        self.fdia_attacks_per_hour.append(hour_attacks)
        self.fdia_blocked_per_hour.append(hour_blocked)

        trades = self.auction.clear_market()

        # Apply trade results to net positions
        residuals = dict(net_after_bess)
        for trade in trades:
            residuals[trade.buyer_id]  += trade.quantity_kwh
            residuals[trade.seller_id] -= trade.quantity_kwh

        # ── SURPLUS PRIORITY 2: Charge BESS with unmatched surplus ─────
        for mg in self.microgrids:
            if residuals[mg.id] > 0.01:
                absorbed = mg.charge_own_bess(residuals[mg.id])
                residuals[mg.id] -= absorbed

        # Track battery SOC
        for mg in self.microgrids:
            self.battery_soc_per_hour[mg.id].append(mg.battery.soc)
            hour_record['microgrids'][mg.id] = {
                'name':           mg.name,
                'generation_kw':  round(raw_gen[mg.id], 3),
                'load_kw':        round(raw_load[mg.id], 3),
                'net_after_bess': round(net_after_bess[mg.id], 3),
                'residual':       round(residuals[mg.id], 3),
                'battery_soc':    round(mg.battery.soc, 3),
                'blacklisted':    mg.id in self.blacklist,
            }

        # ── Record trades on blockchain ────────────────────────────────
        hour_p2p_energy = 0.0
        for trade in trades:
            self.blockchain.add_trade(trade)
            hour_p2p_energy += trade.quantity_kwh
            self.all_trades_log.append(trade)
            hour_record['trades'].append({
                'seller_id':   trade.seller_id,
                'seller_name': trade.seller_name,
                'buyer_id':    trade.buyer_id,
                'buyer_name':  trade.buyer_name,
                'qty_kwh':     trade.quantity_kwh,
                'price':       trade.price_per_kwh,
                'total_usd':   round(trade.quantity_kwh * trade.price_per_kwh, 4),
            })

        self.trades_per_hour.append(len(trades))
        self.clearing_prices.append(self.auction.clearing_price if trades else None)
        self.p2p_energy_per_hour.append(hour_p2p_energy)

        if self.blockchain.pending_transactions:
            eligible = [mg.id for mg in self.microgrids
                        if mg.id in self.blockchain.authorized_nodes]
            if eligible:
                validator = random.choice(eligible)
                self.blockchain.mine_block(validator, hour)

        # ── SURPLUS P3 / DEFICIT P3: Main Grid for residuals ──────────
        hour_import = 0.0
        hour_export = 0.0
        for mg in self.microgrids:
            residual = residuals[mg.id]
            if abs(residual) > 0.01:
                cost = self.main_grid.exchange(residual)
                if residual < 0:
                    hour_import += abs(residual)
                else:
                    hour_export += residual
                hour_record['grid_exchanges'][mg.id] = {
                    'energy_kwh': round(residual, 3),
                    'cost_usd':   round(cost, 4),
                }

        self.grid_import_per_hour.append(hour_import)
        self.grid_export_per_hour.append(hour_export)
        self.hourly_data.append(hour_record)
        return hour_record

    # ------------------------------------------------------------------
    def run_simulation(self, hours: int = 24) -> Dict:
        print("=" * 70)
        print("  BLOCKCHAIN-BASED P2P ENERGY TRADING SIMULATION + FDIA SECURITY")
        print("=" * 70)
        print(f"  Microgrids       : {len(self.microgrids)}")
        print(f"  Simulation       : {hours} hours")
        print(f"  Market Mechanism : Double Auction")
        print(f"  Settlement       : Permissioned Blockchain")
        print(f"  Security Layer   : FDIA Detection + Blacklisting")
        print()
        print("  ┌─ PRIORITY ORDER ───────────────────────────────────────┐")
        print("  │ SURPLUS: P2P Buyers → Own BESS → Main Grid (export)   │")
        print("  │ DEFICIT: Own BESS  → P2P Peers → Main Grid (import)   │")
        print("  └────────────────────────────────────────────────────────┘")
        print()
        print("  ┌─ FDIA SECURITY ────────────────────────────────────────┐")
        print("  │ Detection : Bounds check + Z-score + Price corridor    │")
        print("  │ Penalty   : WARNING (1st) → BLACKLIST (2nd offence)    │")
        print("  └────────────────────────────────────────────────────────┘")
        print("=" * 70)

        weather_pattern = [0.8 + 0.2 * np.sin(np.pi * h / 24) for h in range(hours)]

        for hour in range(hours):
            record   = self.run_hour(hour, weather_pattern[hour])
            n_trades = len(record['trades'])
            if n_trades > 0:
                print(f"\n  ── Hour {hour:02d} ─────────────────────────────────────────────")
                print(f"   Clearing Price: ${self.auction.clearing_price:.4f}/kWh")
                for t in record['trades']:
                    print(f"   ✔ SELLER: {t['seller_id']} ({t['seller_name']:<22s}) "
                          f"→ BUYER: {t['buyer_id']} ({t['buyer_name']:<22s}) "
                          f"{t['qty_kwh']:.3f} kWh @ ${t['price']:.4f} = ${t['total_usd']:.4f}")
            else:
                print(f"  Hour {hour:02d}: No P2P trades — balanced locally or via grid")

        # Print blockchain
        self.blockchain.print_chain()

        # Print FDIA security report
        self.fdia.print_security_report()

        ledger = self.blockchain.get_ledger_summary()
        print("\n" + "=" * 70)
        print("  FINAL SIMULATION RESULTS")
        print("=" * 70)
        print(f"  Blockchain Blocks Mined  : {ledger['blocks']}")
        print(f"  Total P2P Trades         : {ledger['total_trades']}")
        print(f"  Total P2P Energy Traded  : {ledger['total_energy_kwh']} kWh")
        print(f"  Total P2P Settlement     : ${ledger['total_value_usd']}")
        print(f"  Main Grid Imported       : {self.main_grid.total_imported:.2f} kWh")
        print(f"  Main Grid Exported       : {self.main_grid.total_exported:.2f} kWh")
        print(f"  Net Grid Cost            : ${self.main_grid.total_cost:.2f}")
        total_fdia   = sum(self.fdia_attacks_per_hour)
        total_blocked = sum(self.fdia_blocked_per_hour)
        print(f"  FDIA Attacks Attempted   : {total_fdia}")
        print(f"  FDIA Attacks Blocked     : {total_blocked}")
        print(f"  Participants Blacklisted : {len(self.blacklist)}")
        print("=" * 70)

        return {
            'hourly_data':          self.hourly_data,
            'blockchain_ledger':    ledger,
            'main_grid':            self.main_grid,
            'clearing_prices':      self.clearing_prices,
            'p2p_energy_per_hour':  self.p2p_energy_per_hour,
            'grid_import_per_hour': self.grid_import_per_hour,
            'grid_export_per_hour': self.grid_export_per_hour,
            'fdia_attacks':         self.fdia_attacks_per_hour,
            'fdia_blocked':         self.fdia_blocked_per_hour,
        }


# =============================================================================
# 7. VISUALIZATIONS  (8 figures — adds FDIA Security chart)
# =============================================================================
def plot_results(sim: EnergyTradingSimulation):
    import os, warnings
    warnings.filterwarnings('ignore', category=UserWarning, message='.*Glyph.*')

    script_dir = os.path.dirname(os.path.abspath(__file__))
    hours      = list(range(24))
    title_kw   = dict(color='white', fontsize=13, fontweight='bold', pad=12)
    label_kw   = dict(color='#9CA3AF', fontsize=10)
    tick_color = '#6B7280'

    def new_fig(title: str, figsize=(13, 6)):
        plt.style.use('seaborn-v0_8-darkgrid')
        fig, ax = plt.subplots(figsize=figsize)
        fig.patch.set_facecolor(DARK)
        try:
            fig.canvas.manager.set_window_title(title)
        except Exception:
            pass
        ax.set_facecolor('#111827')
        ax.tick_params(colors=tick_color, labelsize=9)
        for spine in ax.spines.values():
            spine.set_edgecolor('#374151')
        ax.xaxis.label.set_color('#9CA3AF')
        ax.yaxis.label.set_color('#9CA3AF')
        return fig, ax

    def save_fig(fig, filename):
        path = os.path.join(script_dir, filename)
        fig.savefig(path, dpi=150, bbox_inches='tight', facecolor=DARK)
        print(f"  Saved: {path}")

    # =========================================================================
    # FIGURE 1 — Solar Generation
    # =========================================================================
    fig1, ax1 = new_fig("Figure 1 - Solar Generation per Microgrid")
    for mg in sim.microgrids:
        ax1.plot(hours, sim.solar_per_hour[mg.id],
                 label=f"{mg.id} - {mg.name}",
                 color=MG_COLORS[mg.id], linewidth=2.2)
    ax1.set_title("[SOLAR] Solar Generation per Microgrid (kW)", **title_kw)
    ax1.set_xlabel("Hour of Day", **label_kw)
    ax1.set_ylabel("Generation (kW)", **label_kw)
    ax1.legend(fontsize=8, facecolor='#1F2937', labelcolor='white',
               edgecolor='#374151', loc='upper left')
    ax1.set_xlim(0, 23)
    fig1.tight_layout()
    save_fig(fig1, 'chart1_solar_generation.png')

    # =========================================================================
    # FIGURE 2 — Load Profile
    # =========================================================================
    fig2, ax2 = new_fig("Figure 2 - Load Profile per Microgrid")
    for mg in sim.microgrids:
        ax2.plot(hours, sim.load_per_hour[mg.id],
                 label=f"{mg.id} - {mg.name}",
                 color=MG_COLORS[mg.id], linewidth=2.2, linestyle='--')
    ax2.set_title("[LOAD] Load Profile per Microgrid (kW)", **title_kw)
    ax2.set_xlabel("Hour of Day", **label_kw)
    ax2.set_ylabel("Load (kW)", **label_kw)
    ax2.legend(fontsize=8, facecolor='#1F2937', labelcolor='white', edgecolor='#374151')
    ax2.set_xlim(0, 23)
    fig2.tight_layout()
    save_fig(fig2, 'chart2_load_profile.png')

    # =========================================================================
    # FIGURE 3 — Battery State of Charge
    # =========================================================================
    fig3, ax3 = new_fig("Figure 3 - Battery State of Charge")
    for mg in sim.microgrids:
        ax3.plot(hours, [s * 100 for s in sim.battery_soc_per_hour[mg.id]],
                 label=f"{mg.id} - {mg.name}",
                 color=MG_COLORS[mg.id], linewidth=2.2)
    ax3.axhline(10, color=RED,   linestyle=':', linewidth=1.4, alpha=0.8, label='Min SOC (10%)')
    ax3.axhline(90, color=ACCENT, linestyle=':', linewidth=1.4, alpha=0.8, label='Max SOC (90%)')
    ax3.set_title("[BESS] Battery State of Charge (%)", **title_kw)
    ax3.set_xlabel("Hour of Day", **label_kw)
    ax3.set_ylabel("SOC (%)", **label_kw)
    ax3.set_ylim(0, 105)
    ax3.legend(fontsize=8, facecolor='#1F2937', labelcolor='white', edgecolor='#374151')
    ax3.set_xlim(0, 23)
    fig3.tight_layout()
    save_fig(fig3, 'chart3_battery_soc.png')

    # =========================================================================
    # FIGURE 4 — P2P Energy Traded + Clearing Price (twin axes)
    # =========================================================================
    fig4, ax4 = new_fig("Figure 4 - P2P Energy Traded & Clearing Price")
    ax4.bar(hours, sim.p2p_energy_per_hour, color=ACCENT, alpha=0.8, width=0.7,
            label='P2P Energy (kWh)')
    ax4.set_title("[P2P] P2P Energy Traded per Hour & Clearing Price", **title_kw)
    ax4.set_xlabel("Hour of Day", **label_kw)
    ax4.set_ylabel("P2P Energy (kWh)", **label_kw)
    ax4b = ax4.twinx()
    valid_hours  = [h for h, p in enumerate(sim.clearing_prices) if p is not None]
    valid_prices = [p for p in sim.clearing_prices if p is not None]
    if valid_prices:
        ax4b.scatter(valid_hours, valid_prices, color=YELLOW, zorder=5, s=50,
                     label='Clearing price')
        ax4b.plot(valid_hours, valid_prices, color=YELLOW, linewidth=1.5, alpha=0.6)
        ax4b.set_ylabel("Clearing Price ($/kWh)", color=YELLOW, fontsize=10)
        ax4b.tick_params(axis='y', colors=YELLOW, labelsize=9)
    ax4b.set_xlim(0, 23)
    ax4.set_xlim(0, 23)
    lines1, labels1 = ax4.get_legend_handles_labels()
    lines2, labels2 = ax4b.get_legend_handles_labels()
    ax4.legend(lines1 + lines2, labels1 + labels2,
               fontsize=8, facecolor='#1F2937', labelcolor='white', edgecolor='#374151')
    fig4.tight_layout()
    save_fig(fig4, 'chart4_p2p_traded.png')

    # =========================================================================
    # FIGURE 5 — Main Grid Import / Export
    # =========================================================================
    fig5, ax5 = new_fig("Figure 5 - Main Grid Interaction")
    ax5.bar(hours, sim.grid_import_per_hour, color=RED,   alpha=0.85, width=0.4,
            label='Import from Grid', align='center')
    ax5.bar([h + 0.4 for h in hours], sim.grid_export_per_hour, color=ACCENT, alpha=0.85,
            width=0.4, label='Export to Grid', align='center')
    ax5.set_title("[GRID] Main Grid Interaction per Hour (kWh)", **title_kw)
    ax5.set_xlabel("Hour of Day", **label_kw)
    ax5.set_ylabel("Energy (kWh)", **label_kw)
    ax5.legend(fontsize=9, facecolor='#1F2937', labelcolor='white', edgecolor='#374151')
    ax5.set_xlim(-0.5, 23.5)
    fig5.tight_layout()
    save_fig(fig5, 'chart5_grid_interaction.png')

    # =========================================================================
    # FIGURE 6 — P2P Trade Flow Heatmap
    # =========================================================================
    fig6, ax6 = new_fig("Figure 6 - P2P Trade Flow Heatmap", figsize=(8, 6))
    mg_ids       = [mg.id for mg in sim.microgrids]
    trade_matrix = np.zeros((5, 5))
    for trade in sim.all_trades_log:
        i = mg_ids.index(trade.seller_id)
        j = mg_ids.index(trade.buyer_id)
        trade_matrix[i, j] += trade.quantity_kwh
    im = ax6.imshow(trade_matrix, cmap='YlOrRd', aspect='auto')
    ax6.set_xticks(range(5)); ax6.set_yticks(range(5))
    ax6.set_xticklabels(mg_ids, color='white', fontsize=9)
    ax6.set_yticklabels(mg_ids, color='white', fontsize=9)
    ax6.set_xlabel("Buyer Microgrid", **label_kw)
    ax6.set_ylabel("Seller Microgrid", **label_kw)
    ax6.set_title("[HEATMAP] P2P Trade Flow Heatmap (kWh Sold → Bought)", **title_kw)
    for i in range(5):
        for j in range(5):
            if trade_matrix[i, j] > 0:
                ax6.text(j, i, f"{trade_matrix[i, j]:.1f}",
                         ha='center', va='center', fontsize=9,
                         color='black', fontweight='bold')
    plt.colorbar(im, ax=ax6, label='kWh traded', shrink=0.85)
    fig6.tight_layout()
    save_fig(fig6, 'chart6_trade_heatmap.png')

    # =========================================================================
    # FIGURE 7 — Blockchain Block Timeline
    # =========================================================================
    fig7, ax7 = new_fig("Figure 7 - Blockchain Block Timeline", figsize=(14, 6))
    block_nums, block_trades, block_energy, block_validators = [], [], [], []
    for blk in sim.blockchain.chain[1:]:
        btx = blk.transactions
        block_nums.append(blk.index)
        block_trades.append(len(btx))
        block_energy.append(sum(t['quantity_kwh'] for t in btx))
        block_validators.append(blk.validator)
    if block_nums:
        colors_bar = [MG_COLORS.get(v, SECONDARY) for v in block_validators]
        bars7 = ax7.bar(block_nums, block_energy, color=colors_bar, alpha=0.88, width=0.55)
        for rect, n_tx, eng, val in zip(bars7, block_trades, block_energy, block_validators):
            bx = rect.get_x() + rect.get_width() / 2
            ax7.text(bx, rect.get_height() + 0.08,
                     f"Block #{int(rect.get_x() + rect.get_width()/2)}\n"
                     f"{n_tx} tx | {eng:.2f} kWh\nValidator: {val}",
                     ha='center', va='bottom', fontsize=7.5, color='white', linespacing=1.4)
        seen = {}
        for val, col in zip(block_validators, colors_bar):
            if val not in seen:
                seen[val] = col
        patches = [mpatches.Patch(color=c, label=f"Validated by {v}") for v, c in seen.items()]
        ax7.legend(handles=patches, fontsize=8, facecolor='#1F2937',
                   labelcolor='white', edgecolor='#374151')
    ax7.set_title("[CHAIN] Blockchain Blocks — Energy Settled per Block (kWh)", **title_kw)
    ax7.set_xlabel("Block Number", **label_kw)
    ax7.set_ylabel("Energy Settled (kWh)", **label_kw)
    if block_nums:
        ax7.set_xticks(block_nums)
        ax7.set_xlim(0.3, max(block_nums) + 0.7)
    fig7.tight_layout()
    save_fig(fig7, 'chart7_blockchain_blocks.png')

    # =========================================================================
    # FIGURE 8 — FDIA Security Dashboard  (NEW)
    # =========================================================================
    fig8, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig8.patch.set_facecolor(DARK)
    try:
        fig8.canvas.manager.set_window_title("Figure 8 - FDIA Security Dashboard")
    except Exception:
        pass

    # Left panel — attacks vs blocked per hour
    ax8a = axes[0]
    ax8a.set_facecolor('#111827')
    ax8a.tick_params(colors=tick_color, labelsize=9)
    for spine in ax8a.spines.values():
        spine.set_edgecolor('#374151')

    x = np.array(hours)
    ax8a.bar(x - 0.2, sim.fdia_attacks_per_hour, width=0.4,
             color=CRIMSON, alpha=0.85, label='FDIA Attacks Attempted')
    ax8a.bar(x + 0.2, sim.fdia_blocked_per_hour, width=0.4,
             color=ACCENT,  alpha=0.85, label='FDIA Attacks Blocked')
    ax8a.set_title("[FDIA] Attack Attempts vs Blocked per Hour", **title_kw)
    ax8a.set_xlabel("Hour of Day", **label_kw)
    ax8a.set_ylabel("Count", **label_kw)
    ax8a.set_xlim(-0.5, 23.5)
    ax8a.legend(fontsize=9, facecolor='#1F2937', labelcolor='white', edgecolor='#374151')

    # Right panel — per-microgrid offence tally
    ax8b = axes[1]
    ax8b.set_facecolor('#111827')
    ax8b.tick_params(colors=tick_color, labelsize=9)
    for spine in ax8b.spines.values():
        spine.set_edgecolor('#374151')

    mg_ids_list   = [mg.id for mg in sim.microgrids]
    mg_names_list = [f"{mg.id}\n{mg.name}" for mg in sim.microgrids]
    offence_counts = [sim.fdia.offences.get(mid, 0) for mid in mg_ids_list]
    bar_colors     = [CRIMSON if mid in sim.blacklist else ORANGE for mid in mg_ids_list]
    bars8 = ax8b.bar(mg_ids_list, offence_counts, color=bar_colors, alpha=0.9, width=0.5)

    for rect, mid in zip(bars8, mg_ids_list):
        label = "BLACKLISTED" if mid in sim.blacklist else ""
        if label:
            ax8b.text(rect.get_x() + rect.get_width() / 2,
                      rect.get_height() + 0.05, label,
                      ha='center', va='bottom', fontsize=8,
                      color=CRIMSON, fontweight='bold')

    ax8b.set_title("[FDIA] Offence Count per Microgrid", **title_kw)
    ax8b.set_xlabel("Microgrid", **label_kw)
    ax8b.set_ylabel("Offences Detected", **label_kw)
    ax8b.set_xticklabels(mg_names_list, color='white', fontsize=8)

    # Legend patches
    legend_patches = [
        mpatches.Patch(color=CRIMSON, label='Blacklisted participant'),
        mpatches.Patch(color=ORANGE,  label='Warned participant'),
    ]
    ax8b.legend(handles=legend_patches, fontsize=9, facecolor='#1F2937',
                labelcolor='white', edgecolor='#374151')

    fig8.tight_layout()
    save_fig(fig8, 'chart8_fdia_security.png')

    print("\n  Opening 8 separate chart windows...")
    plt.show()
    print("  Done.")


# =============================================================================
# 8. ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    random.seed(42)
    np.random.seed(42)

    sim     = EnergyTradingSimulation()
    results = sim.run_simulation(hours=24)
    plot_results(sim)