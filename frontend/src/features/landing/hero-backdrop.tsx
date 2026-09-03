"use client";

import { motion, useReducedMotion } from "framer-motion";

/**
 * The hero's backdrop.
 *
 * Drawn, not photographed. A stock hero image would be someone else's
 * licensing problem, a few hundred kilobytes, soft on a retina screen, and
 * wrong in one of the two themes — and it would say nothing about the product.
 * This is about four kilobytes of vector, sharp at any width, and every colour
 * in it resolves to a design token, so it follows light and dark for free.
 *
 * The composition is the reference material's: a soft horizon of overlapping
 * ridges under a low sun, heavily blurred so it reads as depth and light
 * rather than as illustration. Nothing in it competes with the headline —
 * every band sits below 12% opacity, and the whole thing fades out under the
 * text.
 *
 * The three ridges drift at different speeds and in different directions,
 * which is what makes a still image feel like weather. All of it stops for
 * `prefers-reduced-motion`.
 */
export function HeroBackdrop() {
  const still = useReducedMotion();

  const drift = (x: number, seconds: number) =>
    still
      ? undefined
      : {
          animate: { x: [0, x, 0] },
          transition: {
            duration: seconds,
            repeat: Infinity,
            ease: "easeInOut" as const,
          },
        };

  return (
    <div
      // `z-0`, not a negative z-index. A child at `-z-10` paints *behind* its
      // parent's background under CSS's painting order, and the page wrapper
      // has an opaque `bg-bg` — so the whole scene was being drawn and then
      // covered. The hero's content sits at `z-10` above this.
      className="grain pointer-events-none absolute inset-x-0 top-0 z-0 h-[60rem] overflow-hidden"
      aria-hidden
    >
      <svg
        viewBox="0 0 1440 820"
        preserveAspectRatio="xMidYMid slice"
        className="size-full"
      >
        <defs>
          {/* The sky. Warm at the horizon, colourless at the top — the
              gradient a low sun actually makes, rather than a flat tint.

              Note every colour below is set through `style` rather than a
              `stop-color` attribute. Presentation attributes are not CSS
              properties and do not accept `var()`, so the attribute form
              silently resolves to nothing — the whole backdrop rendered blank
              until this moved. */}
          <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: "var(--bg)" }} />
            <stop offset="55%" style={{ stopColor: "var(--accent-soft)" }} />
            <stop offset="100%" style={{ stopColor: "var(--bg)" }} />
          </linearGradient>

          <radialGradient id="sun" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style={{ stopColor: "var(--accent)", stopOpacity: 0.85 }} />
            <stop offset="45%" style={{ stopColor: "var(--accent)", stopOpacity: 0.32 }} />
            <stop offset="100%" style={{ stopColor: "var(--accent)", stopOpacity: 0 }} />
          </radialGradient>

          <linearGradient id="far" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" style={{ stopColor: "var(--info)", stopOpacity: 0.20 }} />
            <stop offset="60%" style={{ stopColor: "var(--accent)", stopOpacity: 0.30 }} />
            <stop offset="100%" style={{ stopColor: "var(--info)", stopOpacity: 0.17 }} />
          </linearGradient>

          <linearGradient id="mid" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" style={{ stopColor: "var(--accent)", stopOpacity: 0.42 }} />
            <stop offset="50%" style={{ stopColor: "var(--accent)", stopOpacity: 0.26 }} />
            <stop offset="100%" style={{ stopColor: "var(--success)", stopOpacity: 0.20 }} />
          </linearGradient>

          <linearGradient id="near" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" style={{ stopColor: "var(--accent)", stopOpacity: 0.55 }} />
            <stop offset="70%" style={{ stopColor: "var(--accent)", stopOpacity: 0.34 }} />
            <stop offset="100%" style={{ stopColor: "var(--accent)", stopOpacity: 0.46 }} />
          </linearGradient>

          {/* Generous blur. The ridges are drawn as hard paths and softened
              here, which gives a far better falloff than trying to describe
              the same shape with gradient stops. */}
          <filter id="soften" x="-25%" y="-25%" width="150%" height="150%">
            <feGaussianBlur stdDeviation="34" />
          </filter>
          <filter id="soften-near" x="-25%" y="-25%" width="150%" height="150%">
            <feGaussianBlur stdDeviation="22" />
          </filter>

          {/* The whole scene fades before it reaches the headline, so the type
              always sits on near-flat ground. */}
          <linearGradient id="fade" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="white" stopOpacity="0" />
            <stop offset="16%" stopColor="white" stopOpacity="0.9" />
            <stop offset="86%" stopColor="white" stopOpacity="1" />
            <stop offset="100%" stopColor="white" stopOpacity="0.35" />
          </linearGradient>
          <mask id="fade-mask">
            <rect width="1440" height="820" fill="url(#fade)" />
          </mask>
        </defs>

        <g mask="url(#fade-mask)">
          <rect width="1440" height="820" fill="url(#sky)" />

          {/* A low sun, off centre. Centring it would put a bright disc
              directly behind the headline. */}
          <motion.ellipse
            cx="1010"
            cy="470"
            rx="420"
            ry="300"
            fill="url(#sun)"
            {...(still
              ? {}
              : {
                  animate: { cy: [470, 452, 470] },
                  transition: {
                    duration: 24,
                    repeat: Infinity,
                    ease: "easeInOut",
                  },
                })}
          />

          {/* Three ridges, back to front. Each is a single smooth path — the
              silhouette of a landscape rather than a wave, which is what keeps
              it from reading as a generic "blob" background. */}
          <motion.path
            {...drift(26, 34)}
            filter="url(#soften)"
            fill="url(#far)"
            d="M-120 560 C 140 470, 300 520, 470 486 C 660 448, 790 512, 980 470 C 1160 430, 1320 486, 1560 440 L 1560 900 L -120 900 Z"
          />
          <motion.path
            {...drift(-34, 40)}
            filter="url(#soften)"
            fill="url(#mid)"
            d="M-120 646 C 120 586, 286 630, 468 600 C 664 568, 812 626, 1006 596 C 1198 566, 1350 618, 1560 578 L 1560 900 L -120 900 Z"
          />
          <motion.path
            {...drift(18, 28)}
            filter="url(#soften-near)"
            fill="url(#near)"
            d="M-120 736 C 150 690, 330 726, 520 706 C 720 684, 880 730, 1080 710 C 1260 692, 1400 724, 1560 700 L 1560 900 L -120 900 Z"
          />
        </g>
      </svg>

      {/* The last few hundred pixels resolve to the page colour exactly, so the
          hero has no visible edge where the artwork stops. */}
      <div className="absolute inset-x-0 bottom-0 h-56 bg-gradient-to-b from-transparent to-bg" />
    </div>
  );
}
