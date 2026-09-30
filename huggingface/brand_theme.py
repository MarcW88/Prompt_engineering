"""
Charte graphique Semactic pour Gradio Apps
Approche légère : guider Gradio, pas le contraindre
"""

# ============================================
# CONFIGURATION
# ============================================

BRAND_NAME = "Prompt Finder"
BRAND_TAGLINE = "Pipeline GEO Complet"
BRAND_WEBSITE = "https://semactic.com"

# ============================================
# CSS - APPROCHE PROPRE
# ============================================

BRAND_CSS = """
/* =============================================
   SEMACTIC THEME - CLEAN APPROACH
   ============================================= */

/* === 1. DESIGN TOKENS === */
:root {
    --sem-bg: #F8F6F1;
    --sem-card: #ffffff;
    --sem-border: #E8E4DC;
    --sem-text: #1F2937;
    --sem-muted: #6B7280;
    --sem-accent: #F59E0B;
    --sem-accent-hover: #D97706;
}

/* === 2. LAYOUT GLOBAL (léger) === */
.gradio-container {
    background: var(--sem-bg);
    max-width: 1400px;
    margin: auto;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* === 3. CARTES EXPLICITES (classe métier) === */
.sem-card {
    background: var(--sem-card);
    border: 1px solid var(--sem-border);
    border-radius: 12px;
    padding: 1.5rem;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04);
}

/* === 4. COMPOSANTS === */

/* Bouton principal - texte blanc sur orange */
button.primary,
.gradio-container button.primary,
.gradio-container button.lg.primary {
    background: var(--sem-accent) !important;
    background-color: var(--sem-accent) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 8px;
    font-weight: 600;
}

button.primary:hover,
.gradio-container button.primary:hover {
    background: var(--sem-accent-hover) !important;
    background-color: var(--sem-accent-hover) !important;
    color: #ffffff !important;
}

/* Labels */
label {
    color: var(--sem-muted);
    font-weight: 500;
}

/* Titres */
h1, h2, h3 {
    color: var(--sem-text);
}

/* Inputs - juste les couleurs */
input[type="text"], input[type="number"], textarea, select {
    border-color: var(--sem-border);
}

input:focus, textarea:focus {
    border-color: var(--sem-accent);
    outline: none;
    box-shadow: 0 0 0 2px rgba(245, 158, 11, 0.15);
}

/* Sliders - orange */
input[type="range"],
.gradio-container input[type="range"] {
    accent-color: var(--sem-accent) !important;
}

/* Slider track & thumb Gradio specific */
.gradio-container .range-slider input,
.gradio-container input[type="range"]::-webkit-slider-thumb {
    background: var(--sem-accent) !important;
    border: 2px solid white !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.2) !important;
}

.gradio-container input[type="range"]::-moz-range-thumb {
    background: var(--sem-accent) !important;
    border: 2px solid white !important;
}

/* Gradio 4.x slider styling */
.gradio-container .slider-container input[type="range"],
.gradio-container .gr-slider input[type="range"] {
    -webkit-appearance: none;
    appearance: none;
    height: 6px;
    background: #E5E7EB;
    border-radius: 3px;
}

.gradio-container .slider-container input[type="range"]::-webkit-slider-thumb,
.gradio-container .gr-slider input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: var(--sem-accent) !important;
    cursor: pointer;
    border: 2px solid white;
    box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

/* Progress fill for slider - Gradio uses a separate element */
.gradio-container .slider-container .progress,
.gradio-container .gr-slider .progress,
.gradio-container [data-testid="slider"] .progress {
    background: var(--sem-accent) !important;
}

/* Checkboxes */
input[type="checkbox"],
.gradio-container input[type="checkbox"] {
    accent-color: var(--sem-text) !important;
}

/* Tabs - style léger */
.tab-nav {
    border-bottom: 1px solid var(--sem-border);
}

.tab-nav button {
    color: var(--sem-muted);
}

.tab-nav button.selected {
    color: var(--sem-text);
    border-bottom: 2px solid var(--sem-text);
}

/* Progress */
.progress-bar {
    background: var(--sem-accent);
}
"""


# ============================================
# HEADER HTML
# ============================================

def get_header(title: str = None, subtitle: str = None) -> str:
    """Header style Lead Details avec logo image"""
    return f"""
    <div style="padding: 0 0 1.5rem 0; border-bottom: 1px solid #E8E4DC; margin-bottom: 1.5rem;">
        <div style="display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0.5rem;">
            <img src="file/logo_semactic.jpeg" alt="Semactic" style="height: 40px; width: auto; border-radius: 8px;" onerror="this.style.display='none'">
        </div>
        <h1 style="font-size: 1.25rem; font-weight: 600; color: #1F2937; margin: 0.5rem 0 0.25rem 0;">{title or BRAND_NAME}</h1>
        <p style="color: #6B7280; font-size: 0.9rem; margin: 0;">{subtitle or BRAND_TAGLINE}</p>
    </div>
    """


def get_footer() -> str:
    """Footer simple"""
    year = __import__('datetime').datetime.now().year
    return f"""
    <div style="text-align: center; padding: 2rem 0; margin-top: 2rem; border-top: 1px solid #E8E4DC; color: #6B7280; font-size: 0.875rem;">
        <p style="margin: 0;">Powered by <strong style="color: #1F2937;">Semactic</strong></p>
        <p style="margin: 0.5rem 0 0 0; opacity: 0.7;">© {year} Semactic</p>
    </div>
    """


BRAND_HEADER = get_header()
BRAND_FOOTER = get_footer()


# ============================================
# FONCTION D'APPLICATION
# ============================================

def apply_theme(
    title: str,
    subtitle: str = None,
    show_logo: bool = True,
    show_footer: bool = True
) -> dict:
    """
    Retourne les éléments pour appliquer le thème à une app Gradio.
    
    Usage:
        theme = apply_theme("Mon App", "Description de l'app")
        
        with gr.Blocks(css=theme['css']) as demo:
            gr.HTML(theme['header'])
            # ... contenu ...
            gr.HTML(theme['footer'])
    """
    return {
        'css': BRAND_CSS,
        'header': get_header(title, subtitle),
        'footer': get_footer() if show_footer else "",
    }
