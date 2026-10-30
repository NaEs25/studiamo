/** @type {import('tailwindcss').Config} */

// Tailwind's opacity modifiers (e.g. bg-amberPrimary/50) only work when a
// color resolves through this rgb(var(...) / <alpha-value>) form. A plain
// var(--color-primary) hex reference silently drops any class that uses an
// opacity modifier, with no build error. See --color-*-rgb in style.css.
function withOpacity(cssVar) {
    return `rgb(var(${cssVar}) / <alpha-value>)`;
}

module.exports = {
    content: ["app/templates/**/*.html", "app/static/js/**/*.js"],
    darkMode: "class",
    future: {
        // Scopes all hover: utilities to @media (hover: hover) so tap on
        // touch devices can't get stuck showing a hover state (and doesn't
        // eat the first tap resolving :hover before a second tap clicks).
        hoverOnlyWhenSupported: true,
    },
    theme: {
        extend: {
            colors: {
                // Sanctioned public palette (Warm Paper Sepia). Values come
                // from app/static/css/style.css's --color-* tokens, not
                // hand-copied hex, so style.css stays the single source of
                // truth.
                paperBg: withOpacity("--color-bg-rgb"),
                paperCard: withOpacity("--color-surface-rgb"),
                paperSurface: withOpacity("--color-surface-2-rgb"),
                paperDeep: withOpacity("--color-surface-deep-rgb"),
                paperBorder: withOpacity("--color-border-rgb"),
                paperBorderStrong: withOpacity("--color-border-strong-rgb"),
                amberPrimary: withOpacity("--color-primary-rgb"),
                amberHover: withOpacity("--color-primary-hover-rgb"),
                uiYellow: withOpacity("--color-ui-yellow-rgb"),
                logoYellow: withOpacity("--color-logo-yellow-rgb"),
                stoneText: withOpacity("--color-text-rgb"),
                stoneMuted: withOpacity("--color-text-muted-rgb"),

                // bugs.html's own near-black dev-tool theme. Distinct key
                // names from the public palette on purpose, it's internal
                // only and isn't tracked by style.css's design tokens.
                darkBg: "#090b10",
                darkCard: "#11141f",
                darkBorder: "#202636",
                primary: "#f59e0b",
                accent: "#fbbf24",

                // Darkened shades so text in these colors passes WCAG AA on the paper
                // background. They extend the default palette: every other step keeps its
                // stock value, and existing classes (text-emerald-600, bg-red-600, ...) pick
                // up the new values without a template change.
                emerald: { 600: "#007E53" },
                red: { 600: "#D71E21" },
                amber: { 600: "#D47200", 700: "#B35208" },
                stone: { 400: "#908A86", 500: "#746D68" },
            },
            // Style-guide radius tokens (values live in style.css). A nested element's radius is
            // its parent's minus the padding between them, never below ds-sm.
            borderRadius: {
                'ds-sm': 'var(--radius-sm)',
                'ds-md': 'var(--radius-md)',
                'ds-lg': 'var(--radius-lg)',
                'ds-xl': 'var(--radius-xl)',
                'ds-2xl': 'var(--radius-2xl)',
            },
            // font-mono keeps Tailwind's default system monospace stack: it only styles
            // short labels (timestamps, percentages, dates), so no webfont is loaded for it.
            fontFamily: {
                sans: ["Outfit", "system-ui", "sans-serif"],
            },
        },
    },
    plugins: [require("@tailwindcss/typography")],
};
