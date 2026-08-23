# Problem Statement  
The codebase is a Shopify theme that enables the sale of eco‑friendly household cleaning products with a modern glassmorphism UI, animated gradient backgrounds, and pre‑built sections such as hero product rotators, product grids with ratings/badges, combo bundles, ingredients showcases, pillars (“how it works”), and cart/disclosure flows. It solves the need for a visually cohesive, interactive storefront that highlights product benefits while integrating Shopify’s checkout.

# Business Context / Objectives  
school owner – The theme is intended for customers purchasing cleaning products and for developers building the store, but specific objectives (e.g., conversion rate targets) are not evident from the code.

# Functional Requirements  
- Glassmorphism UI with animated gradient backgrounds.  
- Hero section featuring a rotating product carousel.  
- Product grid component displaying ratings and badges.  
- Pre‑built combo bundles for quick purchase.  
- Ingredients showcase section.  
- Pillars (“how it works”) explanatory section.  
- Cart drawer with live notifications and disclosures.  
- Responsive sections (e.g., collection list, featured product).  
- Quick‑order list functionality.

# Non-Functional Requirements  
Not aware – No explicit performance or scalability constraints are documented in the provided files.

# Tech Stack  
- **Frontend**: JavaScript (ES6), CSS, Liquid templating engine.  
- **Backend**: Shopify platform only; no custom server code detected.  
- **Deployment**: Hosted on Shopify as a theme.  

# Architecture  
- Modular folder structure: `assets/` for CSS/JS assets, `sections/` for Liquid sections, `snippets/` for reusable components, `templates/` for JSON‑based templates.  
- Centralized configuration via `config/settings_data.json` and schema validation (`settings_schema.json`).  
- Theme built on Shopify Dawn (Liquid) with custom CSS variables and JavaScript modules (e.g., `animations.js`, `base.css`).  

# Shared Vocabulary  
- **glassmorphism** – UI style using semi‑transparent layers.  
- **combo bundles** – Pre‑packaged product sets.  
- **ingredients showcase** – Highlight eco‑friendly ingredients.  
- **pillars** – “How it works” explanatory sections.  
- **cart‑drawer**, **disclosures**, **quick‑order list**.  

# Assumptions  
- All UI components are responsive and rely on CSS variables for theming.  
- Animations are triggered by scroll events via the `animations.js` module.  
- Sections are rendered entirely in Liquid; no custom server‑side logic is present.  
- The theme integrates with Shopify’s built‑in cart, checkout, and product APIs without exposing a separate backend.

# Change Log
- 2026-08-22 19:58 UTC: Cold bootstrap: inferred from codebase, filled gaps via interview