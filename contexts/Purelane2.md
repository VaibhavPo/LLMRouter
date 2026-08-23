# Problem Statement
The codebase implements a custom Shopify theme designed for selling eco-friendly household cleaning products. The primary problem solved is providing a modern, premium, and highly customized e-commerce user experience that emphasizes visual design (Glassmorphism) and detailed product information presentation.

# Business Context / Objectives
This theme is intended for Shopify merchants selling eco-friendly household cleaning products.
The objectives are to:
1. Drive sales through an engaging and visually appealing interface.
2. Establish a premium brand identity using a modern Glassmorphism design system.
3. Facilitate the sale of complex product offerings, such as combo bundles and detailed ingredient information.
4. Support international markets via comprehensive localization features.

# Functional Requirements
The theme provides the following core functionalities:
*   **Product Presentation:** Displaying products using custom cards, featuring ratings, badges, and detailed variant selection (e.g., `component-product-variant-picker.css`, `main-product.liquid`).
*   **Cart Management:** Handling cart display, notifications, and quick ordering features (`cart.js`, `quick-add.js`, `cart-drawer.liquid`).
*   **Search & Discovery:** Implementing predictive search functionality (`predictive-search.js`, `main-search.liquid`).
*   **Content Display:** Showcasing detailed product information, ingredient lists, and collection listings (e.g., `product-info.js`, `section-main-blog.css`).
*   **Bundle/Combo Sales:** Supporting the display and purchase of pre-built product bundles (`purelane-bundles.liquid`).
*   **Localization:** Supporting multiple international languages for content display (`locales/` directory).
*   **Media Display:** Handling image galleries, slideshows, and deferred media displays.

# Non-Functional Requirements
*   **Design Consistency:** Strict adherence to the Glassmorphism UI design system defined in CSS variables and component classes.
*   **Performance:** Animations and dynamic elements must be performant (e.g., scroll-triggered animations).
*   **Scalability:** Must handle internationalization (i18n) for multiple languages efficiently.
*   **Maintainability:** Code must be structured logically using Liquid sections, snippets, and modular JavaScript/CSS files.

# Tech Stack
*   **Platform:** Shopify Theme (Liquid templating language).
*   **Frontend:** HTML, CSS (SCSS/Custom CSS), JavaScript (ES6+).
*   **Design System:** Custom Glassmorphism UI implementation using CSS variables.
*   **Data Management:** JSON files for settings and localization data.

# Architecture
The architecture follows the standard Shopify theme structure:
1.  **Layouts (`layout/`):** Defines the overall page structure (e.g., `theme.liquid`, `password.liquid`).
2.  **Sections (`sections/`):** Modular, reusable components that define specific content blocks (e.g., `main-product.liquid`, `header.liquid`, `cart-drawer.liquid`).
3.  **Snippets (`snippets/`):** Small, reusable Liquid components used within sections (e.g., `product-card.liquid`, `icon-search.liquid`).
4.  **Assets (`assets/`):** Global styling (`base.css`) and interactive logic (`animations.js`).
5.  **Localization:** Separate JSON files manage all language strings and schema definitions.

# Shared Vocabulary
*   **Glassmorphism:** The core visual design philosophy of the theme, characterized by frosted glass effects and transparency.
*   **Pillars:** A section type used to describe the brand's core principles or "how it works."
*   **Bundles/Combos:** Pre-packaged sets of products offered for sale.
*   **Variants:** Different options available for a single product (e.g., size, color).
*   **Facets:** Product attributes used for filtering and searching.

# Assumptions
*   The theme is deployed on the Shopify platform.
*   All necessary Liquid objects (products, collections) are accessible within the theme environment.
*   Localization data (`locales/`) accurately reflects all supported languages.
*   The detected stack (Liquid, JS, CSS) is sufficient for development and maintenance.
*   The `settings_data.json` and `settings_schema.json` files define the theme's configurable options.

# Change Log
- 2026-08-22 20:46 UTC: Cold bootstrap: inferred from codebase, filled gaps via interview