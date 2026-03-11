import { useState, useEffect, createContext, useContext } from "react";

// ── Auth Context ──────────────────────────────────────────────────────────────
const AuthContext = createContext(null);
const useAuth = () => useContext(AuthContext);

// ── Mock Data ─────────────────────────────────────────────────────────────────
const MOCK_STATS = {
  live_transactions_count: 1847,
  pending_settlements: 23,
  total_volume_24h_usd: "284,921.50",
  fraud_alerts_24h: 7,
  recent_transactions: Array.from({ length: 8 }, (_, i) => ({
    id: `txn-${i}`,
    card_masked: `**** **** **** ${1234 + i}`,
    amount_fiat: (Math.random() * 5000 + 50).toFixed(2),
    currency: "USD",
    status: ["SETTLED", "SETTLED", "SETTLED", "PROCESSING", "FAILED", "SETTLED", "REVIEW", "SETTLED"][i],
    fraud_status: ["CLEAR", "CLEAR", "CLEAR", "CLEAR", "BLOCKED", "CLEAR", "REVIEW", "CLEAR"][i],
    created_at: new Date(Date.now() - i * 180000).toISOString(),
  })),
  settlement_breakdown: { USDT: "198432.10", BTC: "2.341", ETH: "18.92" },
};

const MOCK_RATES = {
  BTC: { rate: "64821.50", source: "BINANCE" },
  ETH: { rate: "3482.30", source: "BINANCE" },
  USDT: { rate: "1.0001", source: "COINBASE" },
  BNB: { rate: "578.40", source: "BINANCE" },
};

const MOCK_FRAUD_ALERTS = Array.from({ length: 6 }, (_, i) => ({
  id: `alert-${i}`,
  transaction_id: `txn-${i * 3}`,
  alert_type: ["R01_HIGH_VELOCITY", "R02_LARGE_AMOUNT", "R05_CARD_TESTING", "R04_AMOUNT_VELOCITY", "R07_DECLINED", "R08_MANUAL_ENTRY"][i],
  severity: ["HIGH", "CRITICAL", "HIGH", "MEDIUM", "HIGH", "MEDIUM"][i],
  description: [
    "Card used 12 times in last hour",
    "Transaction amount $47,200 exceeds max limit",
    "Possible card testing: 4 merchants, small amount",
    "Card spent $23,400 in last hour",
    "Transaction was declined by issuer",
    "Card manually entered (not chip/swipe)",
  ][i],
  is_resolved: i > 3,
  created_at: new Date(Date.now() - i * 600000).toISOString(),
}));

// ── Utilities ──────────────────────────────────────────────────────────────────
const formatCurrency = (n) => parseFloat(n).toLocaleString("en-US", { style: "currency", currency: "USD" });
const formatTime = (iso) => {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
};
const formatDate = (iso) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

const STATUS_COLORS = {
  SETTLED: { bg: "#0d2416", text: "#22c55e", dot: "#22c55e" },
  PROCESSING: { bg: "#1a1a08", text: "#eab308", dot: "#eab308" },
  FAILED: { bg: "#1f0a0a", text: "#ef4444", dot: "#ef4444" },
  PENDING: { bg: "#0f1629", text: "#60a5fa", dot: "#60a5fa" },
  REVIEW: { bg: "#1a0d26", text: "#a78bfa", dot: "#a78bfa" },
  BLOCKED: { bg: "#1f0a0a", text: "#f87171", dot: "#f87171" },
  CLEAR: { bg: "#0d2416", text: "#22c55e", dot: "#22c55e" },
  HIGH: { bg: "#1a0a0a", text: "#f97316", dot: "#f97316" },
  CRITICAL: { bg: "#1f0a0a", text: "#ef4444", dot: "#ef4444" },
  MEDIUM: { bg: "#1a1a08", text: "#eab308", dot: "#eab308" },
  LOW: { bg: "#0f1629", text: "#60a5fa", dot: "#60a5fa" },
};

function StatusBadge({ status }) {
  const colors = STATUS_COLORS[status] || { bg: "#1a1a2e", text: "#94a3b8", dot: "#94a3b8" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 10px",
      borderRadius: 20, background: colors.bg, color: colors.text, fontSize: 11,
      fontWeight: 600, letterSpacing: "0.05em", textTransform: "uppercase",
    }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: colors.dot, flexShrink: 0 }} />
      {status}
    </span>
  );
}

// ── Icon Components ───────────────────────────────────────────────────────────
const Icon = ({ path, size = 20, color = "currentColor" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d={path} />
  </svg>
);

const icons = {
  dashboard: "M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z M9 22V12h6v10",
  transactions: "M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
  settlements: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
  merchants: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  fraud: "M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z",
  analytics: "M18 20V10 M12 20V4 M6 20v-6",
  rates: "M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6",
  logout: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9",
};

// ── Stat Card ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, icon, accent = "#6366f1", trend }) {
  return (
    <div style={{
      background: "linear-gradient(135deg, #0f1117 0%, #13151f 100%)",
      border: "1px solid #1e2130",
      borderRadius: 16, padding: "22px 24px",
      position: "relative", overflow: "hidden",
    }}>
      <div style={{ position: "absolute", top: 0, right: 0, width: 120, height: 120, background: `radial-gradient(circle at 100% 0%, ${accent}18 0%, transparent 70%)`, pointerEvents: "none" }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
        <span style={{ color: "#64748b", fontSize: 12, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase" }}>{label}</span>
        <div style={{ width: 38, height: 38, borderRadius: 10, background: `${accent}18`, display: "flex", alignItems: "center", justifyContent: "center" }}>
          <Icon path={icon} size={18} color={accent} />
        </div>
      </div>
      <div style={{ fontSize: 28, fontWeight: 700, color: "#f1f5f9", letterSpacing: "-0.02em", marginBottom: 6, fontFamily: "'SF Mono', 'Fira Code', monospace" }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 12, color: "#475569" }}>{sub}</div>}
      {trend && (
        <div style={{ display: "inline-flex", alignItems: "center", gap: 4, marginTop: 8, padding: "2px 8px", borderRadius: 12, background: trend > 0 ? "#0d2416" : "#1f0a0a", color: trend > 0 ? "#22c55e" : "#ef4444", fontSize: 11, fontWeight: 600 }}>
          {trend > 0 ? "↑" : "↓"} {Math.abs(trend)}% vs yesterday
        </div>
      )}
    </div>
  );
}

// ── Live Ticker ───────────────────────────────────────────────────────────────
function LiveRateTicker({ rates }) {
  return (
    <div style={{
      background: "#080b12", borderBottom: "1px solid #1e2130",
      padding: "8px 32px", display: "flex", gap: 32, alignItems: "center",
      overflowX: "auto",
    }}>
      <span style={{ color: "#374151", fontSize: 10, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", whiteSpace: "nowrap" }}>LIVE RATES</span>
      {Object.entries(rates).map(([crypto, data]) => (
        <div key={crypto} style={{ display: "flex", alignItems: "center", gap: 8, whiteSpace: "nowrap" }}>
          <span style={{ color: "#64748b", fontSize: 12, fontWeight: 600 }}>{crypto}/USD</span>
          <span style={{ color: "#e2e8f0", fontSize: 13, fontWeight: 700, fontFamily: "monospace" }}>
            ${parseFloat(data.rate).toLocaleString()}
          </span>
          <span style={{ fontSize: 10, color: "#22c55e" }}>● {data.source}</span>
        </div>
      ))}
      <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#22c55e", display: "inline-block", animation: "pulse 2s infinite" }} />
        <span style={{ color: "#22c55e", fontSize: 10, fontWeight: 600 }}>LIVE</span>
      </div>
    </div>
  );
}

// ── Sidebar ───────────────────────────────────────────────────────────────────
function Sidebar({ active, setActive }) {
  const navItems = [
    { id: "dashboard", label: "Dashboard", icon: icons.dashboard },
    { id: "transactions", label: "Transactions", icon: icons.transactions },
    { id: "settlements", label: "Settlements", icon: icons.settlements },
    { id: "fraud", label: "Fraud Alerts", icon: icons.fraud, badge: 7 },
    { id: "merchants", label: "Merchants", icon: icons.merchants },
    { id: "analytics", label: "Analytics", icon: icons.analytics },
  ];

  return (
    <div style={{
      width: 240, background: "#080b12", borderRight: "1px solid #1e2130",
      display: "flex", flexDirection: "column", flexShrink: 0,
    }}>
      {/* Logo */}
      <div style={{ padding: "24px 20px 20px", borderBottom: "1px solid #1e2130" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: "linear-gradient(135deg, #6366f1, #8b5cf6)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 18, fontWeight: 800, color: "white",
          }}>₿</div>
          <div>
            <div style={{ color: "#f1f5f9", fontSize: 14, fontWeight: 700, letterSpacing: "-0.01em" }}>CardCrypto</div>
            <div style={{ color: "#374151", fontSize: 10, fontWeight: 500 }}>Settlement Platform</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: "12px 12px" }}>
        {navItems.map(item => (
          <button
            key={item.id}
            onClick={() => setActive(item.id)}
            style={{
              display: "flex", alignItems: "center", gap: 10, width: "100%",
              padding: "10px 12px", borderRadius: 10, border: "none", cursor: "pointer",
              background: active === item.id ? "linear-gradient(135deg, #1e1b4b, #1e1040)" : "transparent",
              color: active === item.id ? "#a78bfa" : "#4b5563",
              fontSize: 13, fontWeight: active === item.id ? 600 : 500,
              marginBottom: 2, transition: "all 0.15s", textAlign: "left",
              borderLeft: active === item.id ? "2px solid #6366f1" : "2px solid transparent",
            }}
          >
            <Icon path={item.icon} size={17} color={active === item.id ? "#6366f1" : "#374151"} />
            <span style={{ flex: 1 }}>{item.label}</span>
            {item.badge && (
              <span style={{ background: "#ef4444", color: "white", fontSize: 9, fontWeight: 700, padding: "2px 6px", borderRadius: 10 }}>
                {item.badge}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* User */}
      <div style={{ padding: "16px", borderTop: "1px solid #1e2130" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
          <div style={{ width: 32, height: 32, borderRadius: "50%", background: "linear-gradient(135deg, #6366f1, #8b5cf6)", display: "flex", alignItems: "center", justifyContent: "center", color: "white", fontSize: 12, fontWeight: 700 }}>A</div>
          <div>
            <div style={{ color: "#e2e8f0", fontSize: 12, fontWeight: 600 }}>Admin</div>
            <div style={{ color: "#374151", fontSize: 10 }}>admin@cardcrypto.io</div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Dashboard Page ────────────────────────────────────────────────────────────
function DashboardPage({ stats }) {
  return (
    <div style={{ padding: "28px 32px", overflowY: "auto", flex: 1 }}>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ color: "#f1f5f9", fontSize: 22, fontWeight: 700, margin: 0, letterSpacing: "-0.02em" }}>Platform Overview</h1>
        <p style={{ color: "#475569", fontSize: 13, margin: "4px 0 0" }}>Real-time card-to-crypto settlement monitoring</p>
      </div>

      {/* Stats Grid */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 28 }}>
        <StatCard label="24h Volume" value={`$${stats.total_volume_24h_usd}`} sub="Card transactions settled" icon={icons.analytics} accent="#6366f1" trend={12} />
        <StatCard label="Transactions" value={stats.live_transactions_count.toLocaleString()} sub="Last 24 hours" icon={icons.transactions} accent="#22c55e" trend={8} />
        <StatCard label="Pending Settlements" value={stats.pending_settlements} sub="Awaiting blockchain" icon={icons.settlements} accent="#f59e0b" />
        <StatCard label="Fraud Alerts" value={stats.fraud_alerts_24h} sub="Unresolved flags" icon={icons.fraud} accent="#ef4444" />
      </div>

      {/* Two column layout */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 20 }}>
        {/* Recent Transactions */}
        <div style={{ background: "linear-gradient(135deg, #0f1117, #13151f)", border: "1px solid #1e2130", borderRadius: 16 }}>
          <div style={{ padding: "18px 24px", borderBottom: "1px solid #1e2130", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ color: "#e2e8f0", fontSize: 14, fontWeight: 600, margin: 0 }}>Recent Transactions</h2>
            <span style={{ color: "#6366f1", fontSize: 12, fontWeight: 500, cursor: "pointer" }}>View all →</span>
          </div>
          <div>
            {stats.recent_transactions.map((txn, i) => (
              <div key={txn.id} style={{
                display: "flex", alignItems: "center", padding: "14px 24px",
                borderBottom: i < stats.recent_transactions.length - 1 ? "1px solid #0d1020" : "none",
                gap: 14,
              }}>
                <div style={{ width: 38, height: 38, borderRadius: 10, background: "#1e2130", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  <Icon path={icons.transactions} size={16} color="#4b5563" />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ color: "#e2e8f0", fontSize: 13, fontWeight: 500, fontFamily: "monospace" }}>{txn.card_masked}</div>
                  <div style={{ color: "#374151", fontSize: 11, marginTop: 2 }}>{formatDate(txn.created_at)}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div style={{ color: "#f1f5f9", fontSize: 14, fontWeight: 600 }}>${parseFloat(txn.amount_fiat).toLocaleString()}</div>
                  <div style={{ fontSize: 11, color: "#475569" }}>{txn.currency}</div>
                </div>
                <StatusBadge status={txn.status} />
              </div>
            ))}
          </div>
        </div>

        {/* Crypto Settlement Breakdown */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ background: "linear-gradient(135deg, #0f1117, #13151f)", border: "1px solid #1e2130", borderRadius: 16, padding: 20 }}>
            <h2 style={{ color: "#e2e8f0", fontSize: 14, fontWeight: 600, margin: "0 0 16px" }}>Settlement Breakdown</h2>
            {Object.entries(stats.settlement_breakdown).map(([crypto, amount]) => (
              <div key={crypto} style={{ marginBottom: 14 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                  <span style={{ color: "#94a3b8", fontSize: 12, fontWeight: 600 }}>{crypto}</span>
                  <span style={{ color: "#e2e8f0", fontSize: 12, fontWeight: 600, fontFamily: "monospace" }}>{parseFloat(amount).toLocaleString()} {crypto}</span>
                </div>
                <div style={{ height: 4, background: "#1e2130", borderRadius: 2 }}>
                  <div style={{
                    height: "100%", borderRadius: 2,
                    background: { USDT: "#22c55e", BTC: "#f59e0b", ETH: "#6366f1" }[crypto] || "#6366f1",
                    width: `${Math.random() * 60 + 30}%`,
                  }} />
                </div>
              </div>
            ))}
          </div>

          <div style={{ background: "linear-gradient(135deg, #0d1a10, #0f1a0d)", border: "1px solid #1a3020", borderRadius: 16, padding: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: "#22c55e" }} />
              <span style={{ color: "#22c55e", fontSize: 11, fontWeight: 700, letterSpacing: "0.06em" }}>SYSTEM OPERATIONAL</span>
            </div>
            <p style={{ color: "#4ade80", fontSize: 12, margin: 0 }}>All settlement engines running normally. Avg settlement time: 2.4s</p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Transactions Page ─────────────────────────────────────────────────────────
function TransactionsPage() {
  const [filter, setFilter] = useState("ALL");
  const statuses = ["ALL", "SETTLED", "PROCESSING", "FAILED", "REVIEW"];

  const allTxns = Array.from({ length: 20 }, (_, i) => ({
    id: `txn-${i}`,
    external_id: `EXT_${Math.random().toString(36).substr(2, 12).toUpperCase()}`,
    card_masked: `**** **** **** ${1000 + i * 17}`,
    card_network: ["VISA", "MASTERCARD", "AMEX"][i % 3],
    amount_fiat: (Math.random() * 8000 + 20).toFixed(2),
    currency: "USD",
    merchant: `MERCH_${(i % 5).toString().padStart(3, "0")}`,
    status: ["SETTLED", "SETTLED", "SETTLED", "PROCESSING", "FAILED", "REVIEW"][i % 6],
    fraud_score: (Math.random() * 40).toFixed(1),
    created_at: new Date(Date.now() - i * 240000).toISOString(),
  }));

  const filtered = filter === "ALL" ? allTxns : allTxns.filter(t => t.status === filter);

  return (
    <div style={{ padding: "28px 32px", overflowY: "auto", flex: 1 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ color: "#f1f5f9", fontSize: 22, fontWeight: 700, margin: 0 }}>Transactions</h1>
          <p style={{ color: "#475569", fontSize: 13, margin: "4px 0 0" }}>All card payment transactions</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {statuses.map(s => (
            <button key={s} onClick={() => setFilter(s)} style={{
              padding: "7px 14px", borderRadius: 8, border: "1px solid",
              borderColor: filter === s ? "#6366f1" : "#1e2130",
              background: filter === s ? "#1e1b4b" : "transparent",
              color: filter === s ? "#a78bfa" : "#475569",
              fontSize: 12, fontWeight: 600, cursor: "pointer",
            }}>{s}</button>
          ))}
        </div>
      </div>

      <div style={{ background: "linear-gradient(135deg, #0f1117, #13151f)", border: "1px solid #1e2130", borderRadius: 16, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #1e2130" }}>
              {["Transaction ID", "Card", "Network", "Merchant", "Amount", "Fraud Score", "Status", "Time"].map(h => (
                <th key={h} style={{ padding: "14px 16px", color: "#374151", fontSize: 11, fontWeight: 700, letterSpacing: "0.07em", textTransform: "uppercase", textAlign: "left" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((txn, i) => (
              <tr key={txn.id} style={{ borderBottom: "1px solid #0d1020", transition: "background 0.1s" }}>
                <td style={{ padding: "13px 16px", color: "#6366f1", fontSize: 12, fontFamily: "monospace" }}>{txn.external_id}</td>
                <td style={{ padding: "13px 16px", color: "#94a3b8", fontSize: 12, fontFamily: "monospace" }}>{txn.card_masked}</td>
                <td style={{ padding: "13px 16px" }}><span style={{ color: "#64748b", fontSize: 11, fontWeight: 600 }}>{txn.card_network}</span></td>
                <td style={{ padding: "13px 16px", color: "#64748b", fontSize: 12 }}>{txn.merchant}</td>
                <td style={{ padding: "13px 16px", color: "#f1f5f9", fontSize: 13, fontWeight: 600 }}>${parseFloat(txn.amount_fiat).toLocaleString()}</td>
                <td style={{ padding: "13px 16px" }}>
                  <span style={{ color: parseFloat(txn.fraud_score) > 30 ? "#f97316" : "#22c55e", fontSize: 12, fontWeight: 600 }}>{txn.fraud_score}</span>
                </td>
                <td style={{ padding: "13px 16px" }}><StatusBadge status={txn.status} /></td>
                <td style={{ padding: "13px 16px", color: "#374151", fontSize: 11 }}>{formatTime(txn.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Settlements Page ──────────────────────────────────────────────────────────
function SettlementsPage() {
  const settlements = Array.from({ length: 12 }, (_, i) => ({
    id: `set-${i}`,
    fiat_amount: (Math.random() * 5000 + 100).toFixed(2),
    crypto_currency: ["USDT", "BTC", "ETH"][i % 3],
    crypto_amount: (Math.random() * 2).toFixed(6),
    exchange_rate: ["1.0001", "64821.50", "3482.30"][i % 3],
    tx_hash: `0x${Math.random().toString(16).substr(2, 40)}`,
    network: ["ERC20", "BEP20", "MATIC"][i % 3],
    status: ["COMPLETED", "COMPLETED", "TRANSFERRING", "COMPLETED", "FAILED", "COMPLETED"][i % 6],
    wallet: `0x${Math.random().toString(16).substr(2, 10)}...`,
    completed_at: new Date(Date.now() - i * 300000).toISOString(),
  }));

  return (
    <div style={{ padding: "28px 32px", overflowY: "auto", flex: 1 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ color: "#f1f5f9", fontSize: 22, fontWeight: 700, margin: 0 }}>Crypto Settlements</h1>
        <p style={{ color: "#475569", fontSize: 13, margin: "4px 0 0" }}>Blockchain settlement records and transaction hashes</p>
      </div>

      <div style={{ background: "linear-gradient(135deg, #0f1117, #13151f)", border: "1px solid #1e2130", borderRadius: 16, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #1e2130" }}>
              {["Fiat Amount", "Crypto", "Amount", "Exchange Rate", "Network", "TX Hash", "Wallet", "Status", "Time"].map(h => (
                <th key={h} style={{ padding: "14px 16px", color: "#374151", fontSize: 11, fontWeight: 700, letterSpacing: "0.07em", textTransform: "uppercase", textAlign: "left" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {settlements.map(s => (
              <tr key={s.id} style={{ borderBottom: "1px solid #0d1020" }}>
                <td style={{ padding: "13px 16px", color: "#f1f5f9", fontWeight: 600 }}>${parseFloat(s.fiat_amount).toLocaleString()}</td>
                <td style={{ padding: "13px 16px" }}>
                  <span style={{ color: { USDT: "#22c55e", BTC: "#f59e0b", ETH: "#6366f1" }[s.crypto_currency], fontWeight: 700, fontSize: 13 }}>{s.crypto_currency}</span>
                </td>
                <td style={{ padding: "13px 16px", color: "#94a3b8", fontSize: 12, fontFamily: "monospace" }}>{s.crypto_amount}</td>
                <td style={{ padding: "13px 16px", color: "#64748b", fontSize: 12, fontFamily: "monospace" }}>{s.exchange_rate}</td>
                <td style={{ padding: "13px 16px", color: "#475569", fontSize: 11 }}>{s.network}</td>
                <td style={{ padding: "13px 16px", color: "#6366f1", fontSize: 11, fontFamily: "monospace" }}>{s.tx_hash.substr(0, 14)}...</td>
                <td style={{ padding: "13px 16px", color: "#475569", fontSize: 11, fontFamily: "monospace" }}>{s.wallet}</td>
                <td style={{ padding: "13px 16px" }}><StatusBadge status={s.status} /></td>
                <td style={{ padding: "13px 16px", color: "#374151", fontSize: 11 }}>{formatTime(s.completed_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Fraud Page ────────────────────────────────────────────────────────────────
function FraudPage() {
  const [alerts, setAlerts] = useState(MOCK_FRAUD_ALERTS);

  const resolve = (id) => {
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, is_resolved: true } : a));
  };

  const unresolved = alerts.filter(a => !a.is_resolved);
  const bySeverity = { CRITICAL: 0, HIGH: 0, MEDIUM: 0, LOW: 0 };
  alerts.forEach(a => { if (bySeverity[a.severity] !== undefined) bySeverity[a.severity]++; });

  return (
    <div style={{ padding: "28px 32px", overflowY: "auto", flex: 1 }}>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ color: "#f1f5f9", fontSize: 22, fontWeight: 700, margin: 0 }}>Fraud Detection</h1>
        <p style={{ color: "#475569", fontSize: 13, margin: "4px 0 0" }}>Real-time risk monitoring and alert management</p>
      </div>

      {/* Severity summary */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 28 }}>
        {Object.entries(bySeverity).map(([sev, count]) => (
          <div key={sev} style={{
            background: "linear-gradient(135deg, #0f1117, #13151f)", border: "1px solid #1e2130",
            borderRadius: 12, padding: "16px 20px", textAlign: "center",
          }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: STATUS_COLORS[sev]?.text || "#94a3b8", fontFamily: "monospace" }}>{count}</div>
            <div style={{ color: "#374151", fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase", marginTop: 4 }}>{sev}</div>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {alerts.map(alert => (
          <div key={alert.id} style={{
            background: "linear-gradient(135deg, #0f1117, #13151f)",
            border: `1px solid ${alert.is_resolved ? "#1e2130" : "#1e1030"}`,
            borderRadius: 12, padding: "16px 20px",
            display: "flex", alignItems: "center", gap: 16,
            opacity: alert.is_resolved ? 0.5 : 1,
          }}>
            <div style={{ width: 42, height: 42, borderRadius: 10, background: STATUS_COLORS[alert.severity]?.bg || "#1a1a2e", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <Icon path={icons.fraud} size={18} color={STATUS_COLORS[alert.severity]?.text || "#94a3b8"} />
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                <span style={{ color: "#e2e8f0", fontSize: 13, fontWeight: 600 }}>{alert.alert_type}</span>
                <StatusBadge status={alert.severity} />
                {alert.is_resolved && <StatusBadge status="CLEAR" />}
              </div>
              <p style={{ color: "#64748b", fontSize: 12, margin: 0 }}>{alert.description}</p>
              <div style={{ color: "#374151", fontSize: 11, marginTop: 4 }}>
                Transaction: <span style={{ color: "#6366f1", fontFamily: "monospace" }}>{alert.transaction_id}</span>
                {" · "}{formatDate(alert.created_at)}
              </div>
            </div>
            {!alert.is_resolved && (
              <button onClick={() => resolve(alert.id)} style={{
                padding: "8px 16px", borderRadius: 8, border: "1px solid #1e3040",
                background: "#0d1a2e", color: "#60a5fa", fontSize: 12, fontWeight: 600,
                cursor: "pointer", whiteSpace: "nowrap",
              }}>Mark Resolved</button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Analytics Page ─────────────────────────────────────────────────────────────
function AnalyticsPage() {
  const periods = ["1d", "7d", "30d", "90d"];
  const [period, setPeriod] = useState("7d");

  // Simple bar chart data
  const days = parseInt(period) || 7;
  const chartData = Array.from({ length: Math.min(days, 14) }, (_, i) => ({
    label: new Date(Date.now() - (days - i) * 86400000).toLocaleDateString("en-US", { month: "short", day: "numeric" }),
    volume: Math.random() * 50000 + 10000,
    settled: Math.random() * 40000 + 8000,
  }));

  const maxVal = Math.max(...chartData.map(d => d.volume));

  return (
    <div style={{ padding: "28px 32px", overflowY: "auto", flex: 1 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <h1 style={{ color: "#f1f5f9", fontSize: 22, fontWeight: 700, margin: 0 }}>Analytics</h1>
          <p style={{ color: "#475569", fontSize: 13, margin: "4px 0 0" }}>Volume and settlement performance</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {periods.map(p => (
            <button key={p} onClick={() => setPeriod(p)} style={{
              padding: "7px 14px", borderRadius: 8, border: "1px solid",
              borderColor: period === p ? "#6366f1" : "#1e2130",
              background: period === p ? "#1e1b4b" : "transparent",
              color: period === p ? "#a78bfa" : "#475569",
              fontSize: 12, fontWeight: 600, cursor: "pointer",
            }}>{p}</button>
          ))}
        </div>
      </div>

      {/* Chart */}
      <div style={{ background: "linear-gradient(135deg, #0f1117, #13151f)", border: "1px solid #1e2130", borderRadius: 16, padding: "24px", marginBottom: 20 }}>
        <h3 style={{ color: "#94a3b8", fontSize: 12, fontWeight: 600, letterSpacing: "0.07em", textTransform: "uppercase", margin: "0 0 20px" }}>Transaction Volume (USD)</h3>
        <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 160 }}>
          {chartData.map((d, i) => (
            <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
              <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 2, height: 140, justifyContent: "flex-end" }}>
                <div style={{
                  width: "100%",
                  height: `${(d.settled / maxVal) * 120}px`,
                  background: "linear-gradient(to top, #4338ca, #6366f1)",
                  borderRadius: "4px 4px 0 0",
                  minHeight: 4,
                }} />
              </div>
              <span style={{ color: "#374151", fontSize: 9, textAlign: "center", transform: "rotate(-45deg)", whiteSpace: "nowrap" }}>{d.label}</span>
            </div>
          ))}
        </div>
        <div style={{ display: "flex", gap: 20, marginTop: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: "#6366f1" }} />
            <span style={{ color: "#475569", fontSize: 11 }}>Settled Volume</span>
          </div>
        </div>
      </div>

      {/* KPI Cards */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
        {[
          { label: "Total Volume", value: "$284,921", sub: "Last 7 days", accent: "#6366f1" },
          { label: "Success Rate", value: "98.4%", sub: "Settlement success", accent: "#22c55e" },
          { label: "Avg Transaction", value: "$342.18", sub: "Per transaction", accent: "#f59e0b" },
          { label: "Fraud Block Rate", value: "0.38%", sub: "Of all transactions", accent: "#ef4444" },
          { label: "BTC Settled", value: "4.23 BTC", sub: "This period", accent: "#f59e0b" },
          { label: "USDT Settled", value: "198,432", sub: "USDT this period", accent: "#22c55e" },
        ].map(card => (
          <div key={card.label} style={{ background: "linear-gradient(135deg, #0f1117, #13151f)", border: "1px solid #1e2130", borderRadius: 12, padding: "18px 20px" }}>
            <div style={{ color: "#374151", fontSize: 11, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 8 }}>{card.label}</div>
            <div style={{ color: card.accent, fontSize: 24, fontWeight: 700, fontFamily: "monospace" }}>{card.value}</div>
            <div style={{ color: "#374151", fontSize: 11, marginTop: 4 }}>{card.sub}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [active, setActive] = useState("dashboard");
  const [rates, setRates] = useState(MOCK_RATES);
  const [stats] = useState(MOCK_STATS);

  // Simulate live rate updates
  useEffect(() => {
    const interval = setInterval(() => {
      setRates(prev => {
        const updated = { ...prev };
        updated.BTC = { ...prev.BTC, rate: (parseFloat(prev.BTC.rate) + (Math.random() - 0.5) * 50).toFixed(2) };
        updated.ETH = { ...prev.ETH, rate: (parseFloat(prev.ETH.rate) + (Math.random() - 0.5) * 10).toFixed(2) };
        return updated;
      });
    }, 3000);
    return () => clearInterval(interval);
  }, []);

  const pages = {
    dashboard: <DashboardPage stats={stats} />,
    transactions: <TransactionsPage />,
    settlements: <SettlementsPage />,
    fraud: <FraudPage />,
    analytics: <AnalyticsPage />,
    merchants: (
      <div style={{ padding: "28px 32px", color: "#94a3b8" }}>
        <h1 style={{ color: "#f1f5f9", fontSize: 22, fontWeight: 700, margin: "0 0 8px" }}>Merchants</h1>
        <p style={{ color: "#475569", fontSize: 13 }}>Merchant KYC, wallet management, and settlement configuration.</p>
        <div style={{ background: "linear-gradient(135deg, #0f1117, #13151f)", border: "1px solid #1e2130", borderRadius: 16, padding: 24, marginTop: 20 }}>
          <p style={{ color: "#475569", margin: 0 }}>Connect to the backend API to load merchant data. Merchant onboarding includes KYC verification, wallet configuration, and settlement preferences.</p>
        </div>
      </div>
    ),
  };

  return (
    <div style={{
      display: "flex", flexDirection: "column", height: "100vh",
      background: "#080b12", fontFamily: "'Inter', 'SF Pro Display', system-ui, sans-serif",
      color: "#f1f5f9",
    }}>
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #080b12; }
        ::-webkit-scrollbar-thumb { background: #1e2130; border-radius: 2px; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
        button:hover { opacity: 0.85; }
      `}</style>

      <LiveRateTicker rates={rates} />

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        <Sidebar active={active} setActive={setActive} />
        <main style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          {pages[active] || pages.dashboard}
        </main>
      </div>
    </div>
  );
}
