"use client";

import { motion, useReducedMotion, type Variants } from "framer-motion";
import type { ReactNode } from "react";

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
        <span key={`${word}-${i}`} className="inline-block overflow-hidden align-bottom">
          <motion.span
            aria-hidden
            className="inline-block"
            variants={{
              hidden: { y: "108%" },
              shown: { y: 0, transition: { duration: 0.75, ease: EASE } },
            }}
          >
            {word}
            {" "}
          </motion.span>
        </span>
      ))}
    </motion.span>
  );
}
