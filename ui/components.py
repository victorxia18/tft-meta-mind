"""Custom HTML components for TFT Meta Mind UI."""


def render_header() -> str:
    """Render the main page header with decorative glyph and animations."""
    return """
    <div style="animation: fadeInDown 0.6s ease-out both; margin-bottom: 0.2rem;">
        <span style="
            font-size: 2.4rem;
            font-family: 'Clash Display', sans-serif;
            font-weight: 700;
            background: linear-gradient(135deg, #C89B3C 0%, #E8C969 50%, #C89B3C 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            letter-spacing: -0.5px;
        ">&#x2726; TFT Meta Mind</span>
    </div>
    <div style="
        animation: fadeInDown 0.6s ease-out 0.15s both;
        font-family: 'DM Sans', sans-serif;
        font-size: 1.0rem;
        color: #8B8D94;
        margin-top: 0;
        margin-bottom: 1.5rem;
        letter-spacing: 0.3px;
    ">AI-powered TFT meta analyst &mdash; powered by real-time data</div>
    """


def render_welcome() -> str:
    """Render a styled welcome message for the chat."""
    return """
    <div style="animation: messageIn 0.4s ease-out both;">
        <p style="
            font-family: 'Clash Display', sans-serif;
            font-size: 1.15rem;
            font-weight: 500;
            color: #C89B3C;
            margin-bottom: 0.4rem;
        ">Welcome, Tactician.</p>
        <p style="
            font-family: 'DM Sans', sans-serif;
            font-size: 1.02rem;
            color: #E8E6E3;
            line-height: 1.65;
        ">I'm <strong>TFT Meta Mind</strong> &mdash; your AI-powered TFT analyst.
        Ask me anything about the current meta: best comps, unit tier lists,
        item recommendations, or how to climb. What do you want to know?</p>
    </div>
    """
