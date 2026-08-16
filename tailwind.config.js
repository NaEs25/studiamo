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
            },
            fontFamily: {
                sans: ["Outfit", "Inter", "sans-serif"],
                mono: ["JetBrains Mono", "monospace"],
            },
        },
    },
    plugins: [require("@tailwindcss/typography")],
};
