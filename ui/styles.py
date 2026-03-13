"""Custom CSS design system for TFT Meta Mind — Dark Fantasy Luxe theme."""

CUSTOM_CSS = """
<style>
/* ── Font imports ─────────────────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&family=JetBrains+Mono:wght@400;500&display=swap');
@import url('https://api.fontshare.com/v2/css?f[]=clash-display@400,500,600,700&display=swap');

/* ── Design tokens ────────────────────────────────────── */
:root {
    --bg-void: #0a0a12;
    --bg-surface: #111119;
    --bg-elevated: #1a1a25;
    --bg-glass: rgba(18, 18, 30, 0.6);
    --gold: #C89B3C;
    --gold-bright: #E8C969;
    --gold-dim: #8B6914;
    --arcane: #7B68EE;
    --arcane-glow: #9B8AFE;
    --text-primary: #E8E6E3;
    --text-secondary: #8B8D94;
    --text-muted: #555562;
    --font-display: 'Clash Display', 'DM Sans', sans-serif;
    --font-body: 'DM Sans', sans-serif;
    --font-mono: 'JetBrains Mono', monospace;
}

/* ── Base typography ──────────────────────────────────── */
html, body, [class*="css"] {
    font-family: var(--font-body) !important;
}
h1, h2, h3, h4, h5, h6 {
    font-family: var(--font-display) !important;
}
code, pre, .stCode {
    font-family: var(--font-mono) !important;
}

/* ── Animations ───────────────────────────────────────── */
@keyframes fadeInUp {
    from { opacity: 0; transform: translateY(16px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes fadeInDown {
    from { opacity: 0; transform: translateY(-12px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes messageIn {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
}
@keyframes shimmer {
    0%   { background-position: -200% center; }
    100% { background-position: 200% center; }
}
@keyframes subtlePulse {
    0%, 100% { opacity: 0.4; }
    50%      { opacity: 0.6; }
}

/* ── Noise grain overlay ──────────────────────────────── */
.stApp::after {
    content: "";
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    opacity: 0.03;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
    background-repeat: repeat;
    background-size: 256px 256px;
}

/* ── Animated shimmer accent bar ──────────────────────── */
.stApp::before {
    content: "";
    display: block;
    width: 100%;
    height: 3px;
    background: linear-gradient(
        90deg,
        var(--gold-dim) 0%,
        var(--gold) 15%,
        var(--gold-bright) 30%,
        var(--arcane) 50%,
        var(--arcane-glow) 55%,
        var(--arcane) 60%,
        var(--gold-bright) 70%,
        var(--gold) 85%,
        var(--gold-dim) 100%
    );
    background-size: 200% auto;
    animation: shimmer 8s linear infinite;
    position: fixed;
    top: 0;
    left: 0;
    z-index: 9999;
}

/* ── Nebula background spots ──────────────────────────── */
.stApp > div:first-child {
    background:
        radial-gradient(ellipse 600px 400px at 10% 10%, rgba(123, 104, 238, 0.06) 0%, transparent 70%),
        radial-gradient(ellipse 500px 350px at 90% 90%, rgba(200, 155, 60, 0.04) 0%, transparent 70%),
        var(--bg-void);
}

/* ── Hide default chrome ──────────────────────────────── */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* ── Sidebar ──────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background-color: var(--bg-surface) !important;
    border-right: 1px solid rgba(200, 155, 60, 0.1);
}
section[data-testid="stSidebar"] .stMarkdown {
    color: var(--text-primary);
}
section[data-testid="stSidebar"] .stMarkdown h1 {
    font-family: var(--font-display) !important;
    color: var(--gold);
    font-size: 1.4rem;
    font-weight: 600;
}

.sidebar-header {
    font-family: var(--font-display) !important;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: var(--gold);
    font-weight: 500;
    margin-top: 1rem;
    margin-bottom: 0.5rem;
}

.powered-by {
    font-size: 0.72rem;
    color: var(--text-muted);
    line-height: 1.6;
}

/* Sidebar expander */
section[data-testid="stSidebar"] details {
    background-color: var(--bg-elevated) !important;
    border: 1px solid rgba(200, 155, 60, 0.1) !important;
    border-radius: 8px !important;
}
section[data-testid="stSidebar"] details summary {
    color: var(--text-secondary) !important;
}
section[data-testid="stSidebar"] details summary:hover {
    color: var(--gold) !important;
}

/* Sidebar button */
section[data-testid="stSidebar"] .stButton > button {
    background-color: transparent !important;
    border: 1px solid var(--gold-dim) !important;
    color: var(--gold) !important;
    border-radius: 8px !important;
    transition: all 0.2s ease !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    background-color: rgba(200, 155, 60, 0.1) !important;
    border-color: var(--gold) !important;
}

/* ── Stat cards (glassmorphism) ───────────────────────── */
div[data-testid="stMetric"] {
    background: var(--bg-glass) !important;
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(200, 155, 60, 0.12);
    border-radius: 14px;
    padding: 20px 24px;
    text-align: center;
    transition: all 0.3s ease;
    animation: fadeInUp 0.5s ease-out both;
}
div[data-testid="stMetric"]:nth-child(1) { animation-delay: 0.0s; }
div[data-testid="stMetric"]:nth-child(2) { animation-delay: 0.1s; }
div[data-testid="stMetric"]:nth-child(3) { animation-delay: 0.2s; }
div[data-testid="stMetric"]:nth-child(4) { animation-delay: 0.3s; }

div[data-testid="stMetric"]:hover {
    border-color: rgba(200, 155, 60, 0.35);
    box-shadow: 0 0 20px rgba(200, 155, 60, 0.08), 0 0 40px rgba(200, 155, 60, 0.04);
    transform: translateY(-2px);
}

div[data-testid="stMetric"] label {
    color: var(--text-secondary) !important;
    font-family: var(--font-display) !important;
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 1px;
}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
    color: var(--gold-bright) !important;
    font-family: var(--font-display) !important;
    font-size: 2rem !important;
    font-weight: 700;
}

/* Stagger animation for stat card columns */
div[data-testid="stHorizontalBlock"] > div:nth-child(1) div[data-testid="stMetric"] { animation-delay: 0.0s; }
div[data-testid="stHorizontalBlock"] > div:nth-child(2) div[data-testid="stMetric"] { animation-delay: 0.1s; }
div[data-testid="stHorizontalBlock"] > div:nth-child(3) div[data-testid="stMetric"] { animation-delay: 0.2s; }
div[data-testid="stHorizontalBlock"] > div:nth-child(4) div[data-testid="stMetric"] { animation-delay: 0.3s; }

/* ── Chat messages ────────────────────────────────────── */
.stChatMessage {
    animation: messageIn 0.3s ease-out both;
}

.stChatMessage[data-testid="chat-message-assistant"] {
    background: linear-gradient(135deg, rgba(123, 104, 238, 0.08) 0%, rgba(18, 18, 30, 0.4) 100%) !important;
    border: 1px solid rgba(123, 104, 238, 0.12);
    border-radius: 14px;
    padding: 4px 8px;
}
.stChatMessage[data-testid="chat-message-user"] {
    background: linear-gradient(135deg, rgba(200, 155, 60, 0.06) 0%, rgba(18, 18, 30, 0.3) 100%) !important;
    border: 1px solid rgba(200, 155, 60, 0.1);
    border-radius: 14px;
    padding: 4px 8px;
}

.stChatMessage p {
    font-size: 1.02rem;
    line-height: 1.65;
    color: var(--text-primary);
}

/* ── Chat input ───────────────────────────────────────── */
.stChatInput > div {
    border-color: rgba(200, 155, 60, 0.2) !important;
    background-color: var(--bg-surface) !important;
    border-radius: 12px !important;
}
.stChatInput > div:focus-within {
    border-color: var(--gold) !important;
    box-shadow: 0 0 0 1px var(--gold-dim) !important;
}
.stChatInput textarea {
    color: var(--text-primary) !important;
    font-family: var(--font-body) !important;
}

/* ── Starter question buttons ─────────────────────────── */
.starter-btn button {
    border-radius: 12px !important;
    border: 1px solid rgba(200, 155, 60, 0.2) !important;
    color: var(--text-secondary) !important;
    background: var(--bg-glass) !important;
    backdrop-filter: blur(8px) !important;
    -webkit-backdrop-filter: blur(8px) !important;
    font-family: var(--font-body) !important;
    font-size: 0.85rem !important;
    padding: 8px 16px !important;
    white-space: nowrap !important;
    transition: all 0.25s ease !important;
}
.starter-btn button:hover {
    background: rgba(200, 155, 60, 0.1) !important;
    border-color: var(--gold) !important;
    color: var(--gold-bright) !important;
    box-shadow: 0 0 16px rgba(200, 155, 60, 0.1) !important;
}

/* ── Spinner ──────────────────────────────────────────── */
.stSpinner > div {
    border-top-color: var(--arcane) !important;
}

/* ── Dividers ─────────────────────────────────────────── */
hr {
    border-color: rgba(200, 155, 60, 0.08) !important;
}

/* ── Custom scrollbar ─────────────────────────────────── */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: var(--bg-void);
}
::-webkit-scrollbar-thumb {
    background: var(--gold-dim);
    border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--gold);
}

/* ── Main content expanders ───────────────────────────── */
details {
    border: 1px solid rgba(123, 104, 238, 0.1) !important;
    border-radius: 10px !important;
    background-color: var(--bg-surface) !important;
}

/* ── Warning/error/success boxes ──────────────────────── */
.stAlert {
    border-radius: 10px !important;
}

/* ── Links ────────────────────────────────────────────── */
a {
    color: var(--arcane-glow) !important;
    text-decoration: none;
    transition: color 0.2s ease;
}
a:hover {
    color: var(--gold-bright) !important;
}
</style>
"""
