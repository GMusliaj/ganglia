---
type: lesson
title: Refactor interactions in small verified steps
description: Preserve working behavior during UI refactors by changing one interaction boundary at a time and rerunning real-browser regression checks after each step.
tags: [visualization, workflow]
date: 2026-08-27
---

# Refactor interactions in small verified steps

## Active

**Treat every structural UI refactor as a behavior-preservation exercise.**

A large rewrite can leave the page looking correct while breaking established
interactions. Unit tests and synthetic DOM events are insufficient when the
behavior depends on layering, hit targets, pointer propagation, drag handlers,
focus, responsive panels, or browser navigation.

Refactor one boundary at a time:

1. Capture a small functional baseline for the current behavior.
2. Make one cohesive change, such as extracting UI files, changing delivery,
   or redesigning a control.
3. Rebuild and exercise the affected path with real browser input.
4. Keep the change only after the baseline still passes.
5. Add the discovered failure mode to the regression suite before continuing.

For an interactive graph, the minimum behavior matrix covers:

- real pointer selection and a persistent detail inspector;
- keyboard selection, visible focus, Escape, and predictable back behavior;
- drag, pan, zoom, fit, search, filters, and relationship navigation;
- responsive library and detail panels with touch-sized targets;
- selected-neighborhood emphasis and correct connection-layer toggles;
- live-reload or delivery changes without losing interaction state
  unexpectedly.

Do not combine delivery architecture, information architecture, visual
redesign, and interaction rewrites into one unverified jump. Iterative changes
make the first regression attributable and cheap to reverse.

## Source

Empirical lesson from repeated interaction regressions during a knowledge-canvas refactor, 2026-08-27.
