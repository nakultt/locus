"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";
import { Fragment, type ReactNode } from "react";

/**
 * The landing page's motion vocabulary.
 *
 * One easing curve, three distances, and a single rule underneath all of it:
 * `useReducedMotion` is read in every component here, and when it is set the
 * animation is not "shortened" — it is replaced by the final state. A reduced
 * 200ms version of a transform still moves, and moving is the thing the setting
 * asks you not to do.
 *
 * Everything reveals on scroll with `once: true`. Content that re-animates each
 * time it re-enters the viewport turns scrolling back up into a slideshow.
 *
 * Every wrapper here carries `data-reveal`, and `globals.css` uses it to force
 * the shown state under `@media print`. A reveal starts at `opacity: 0` and is
 * lifted by an IntersectionObserver, which only fires for content that actually
 * enters the viewport — but printing and Save-as-PDF render the whole document
 * without ever scrolling it, so the observers never fire and everything below
 * the hero comes out blank. Scrolling a real page is fine, including a jump
 * straight to the footer and back; it is specifically no-scroll rendering that
 * breaks, and the attribute is what lets one rule fix it.
 */

const EASE = [0.32, 0.72, 0, 1] as const;

export function Reveal({
  children,
  delay = 0,
  y = 20,
  className,
  as = "div",
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  className?: string;
  as?: "div" | "section" | "li" | "span";
}) {
  const still = useReducedMotion();
  const Tag = motion[as];

  return (
    <Tag
      data-reveal=""
      className={className}
      initial={still ? false : { opacity: 0, y }}
      whileInView={still ? undefined : { opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-80px" }}
      transition={{ duration: 0.6, ease: EASE, delay }}
    >
      {children}
    </Tag>
  );
}

/**
 * A group whose children arrive one after another.
 *
 * The stagger is small — 60ms — because the point is to give a list a direction
 * to be read in, not to make the reader wait for it.
 */
export function RevealGroup({
  children,
  className,
  stagger = 0.06,
  as = "div",
}: {
  children: ReactNode;
  className?: string;
  stagger?: number;
  as?: "div" | "ul" | "ol" | "section";
}) {
  const still = useReducedMotion();
  const Tag = motion[as];

  const variants: Variants = {
    hidden: {},
    shown: { transition: { staggerChildren: stagger } },
  };

  return (
    <Tag
      data-reveal=""
      className={className}
      variants={still ? undefined : variants}
      initial={still ? false : "hidden"}
      whileInView={still ? undefined : "shown"}
      viewport={{ once: true, margin: "-80px" }}
    >
      {children}
    </Tag>
  );
}

export function RevealItem({
  children,
  className,
  as = "div",
  y = 16,
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "li";
  y?: number;
}) {
  const still = useReducedMotion();
  const Tag = motion[as];

  return (
    <Tag
      data-reveal=""
      className={className}
      variants={
        still
          ? undefined
          : {
              hidden: { opacity: 0, y },
              shown: { opacity: 1, y: 0, transition: { duration: 0.55, ease: EASE } },
            }
      }
    >
      {children}
    </Tag>
  );
}

/**
 * A headline that assembles from its own words.
 *
 * Per-word rather than per-letter. Letters arriving one at a time is a effect
 * people have seen a thousand times and it makes a long headline unreadable
 * while it plays; words land fast enough to read as one motion.
 *
 * **The spaces between the words are real, breaking spaces, and that is
 * load-bearing.** Each word is an `inline-block` so it can be masked and slid
 * up, which makes it an *atomic inline*, and the guaranteed soft-wrap
 * opportunity between two atomic inlines is whitespace between them. The first
 * version had neither: the outer spans were butted directly against each other,
 * and the only space in the markup was a **non-breaking** one (U+00A0) sealed
 * inside the masked box at the end of each word. A NBSP does not merely fail to
 * offer a break — it forbids one. Blink breaks between adjacent atomic inlines
 * anyway, so the headline wrapped correctly in every test here; an engine that
 * does not is entitled not to, and there the headline is a single unbreakable
 * line that can only overflow its column. On a phone that renders as the first
 * and last letters sliced off by the screen edges, which is exactly what it did.
 *
 * The space also does not belong inside an `overflow-hidden` box: it is the gap
 * between two words, not part of either, and keeping it there padded every
 * word's measured width with a space the box then clipped.
 */
export function RevealWords({
  text,
  className,
  delay = 0,
}: {
  text: string;
  className?: string;
  delay?: number;
}) {
  const still = useReducedMotion();

  if (still) return <span className={className}>{text}</span>;

  return (
    <motion.span
      className={className}
      initial="hidden"
      animate="shown"
      variants={{ shown: { transition: { staggerChildren: 0.045, delayChildren: delay } } }}
      aria-label={text}
    >
      {text.split(" ").map((word, i) => (
        <Fragment key={`${word}-${i}`}>
          {i > 0 ? " " : null}
          <span className="inline-block overflow-hidden align-bottom pb-[0.25em] -mb-[0.25em]">
            <motion.span
              aria-hidden
              className="inline-block"
              variants={{
                hidden: { y: "135%" },
                shown: { y: 0, transition: { duration: 0.75, ease: EASE } },
              }}
            >
              {word}
            </motion.span>
          </span>
        </Fragment>
      ))}
    </motion.span>
  );
}
