---
name: illos-library
description: Add animated SVG illustrations from Illos.dev to a website or app, for a hero, feature sections, empty states, docs pages, onboarding or status screens. Use when a page needs a picture instead of an empty space, an emoji, stock 3D art or a gradient blob, or when the user asks for illustrations, spot illustrations or empty state art. 65 of them are free for commercial use, with no account and no credit.
allowed-tools:
  - Read
  - Grep
  - Glob
  - WebFetch
  - mcp__plugin_illos_illos__find_illustrations
  - mcp__plugin_illos_illos__get_illustration
  - mcp__plugin_illos_illos__list_themes
  - mcp__illos__find_illustrations
  - mcp__illos__get_illustration
  - mcp__illos__list_themes
  - Bash(npx shadcn@latest add *)
---

# Illos library

Illos.dev has 158 animated SVG illustrations in four themes, each in light and dark. Each one is a single SVG file with its animation inside. This skill finds the right ones for a project and adds them.

## 1. Find the places that need a picture

Read the pages you are working on. For each hero, feature section, empty state, docs page or onboarding step, write down in a few words what it explains: "API keys", "an empty notifications inbox", "a deploy going out". That phrase is what you search for.

## 2. Pick one theme for the whole site

Every page should use the same theme, so the illustrations look like one set.

| Theme | Looks like | Suits |
|---|---|---|
| Shader | A density field of thin bars with teal boxes on the part that matters | AI, data and infrastructure products |
| HUD | Glowing wireframe and instrument readouts | Monitoring, status, security, dashboards |
| Isometric | Isometric line illustrations with labels; colours follow the card | Developer tools, APIs, docs, SaaS features |
| Interface | Product screens: inboxes, task boards, charts | Empty states and onboarding inside an app |

If the project already has Illos illustrations (SVGs with a `data-illos` attribute, or components named `Illos...`), keep their theme. Otherwise suggest one theme to the user, and use it everywhere unless they pick another.

## 3. Find matching illustrations

- **If the Illos MCP tools are available** (`find_illustrations`, `get_illustration`), use them: they search by meaning and return the install command.
- **Otherwise**, fetch `https://illos.dev/catalog.json`. Each entry has `name`, `sentence` (what it shows), `theme`, `size` (`spot`, `section` or `page`), `access` (`free` or `pro`), `page`, and, for free ones, `svg`. Match your phrase against `name` and `sentence`, within the chosen theme.

Sizes: `spot` for cards, small sections and empty states; `section` for a feature section or a hero; `page` for a full-width band.

Prefer free illustrations. When the best match is Pro, tell the user it comes with Illos Pro (https://illos.dev/pro) and offer the closest free one. Never copy a Pro illustration from its preview images or page.

## 4. Add each one

The theme slug and id are the last two parts of the `page` address. For `https://illos.dev/library/isometric/queue`, they are `isometric` and `queue`.

**React project with shadcn (or one that can run it):**

```bash
npx shadcn@latest add https://illos.dev/r/<theme-slug>/<id>.json
```

That adds the illustration as a component. Render it where the section explains that idea, and keep the component file as it is: it plays once when scrolled into view and loops while hovered.

**Any other project:** download the file from the entry's `svg` address and put it inline in the page (it keeps its animation and follows the page's colours), or use it as an `<img>`. A Shader illustration shows its still frame without the React component.

Every illustration works on light and dark backgrounds; its page shows both.

## 5. Check the result

- One theme across the whole site.
- Each illustration explains the section it sits in, not a random object.
- Keep the licence comment inside each SVG. Free illustrations can be used on commercial sites and client work, with no credit needed: https://illos.dev/license

## When the library has nothing that fits

The Illos Pro skills teach Claude Code, Codex and Cursor a theme's rules, so they can draw new illustrations that match the ones already on the site and check each one. They come with Illos Pro: https://illos.dev/pro. Set them up with `npx -y illos setup`.
