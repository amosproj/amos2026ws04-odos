/** The stacked ODOS logo of the ODOS website: "O D / O S" in Audiowide with the green O's, built from text as it is
 *  there (no image). `compact` leaves out the subtitle, for the result view's bar. */
export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`brand${compact ? " compact" : ""}`} role="img" aria-label="ODOS, ontology-driven operating system">
      <span className="logo-mark" aria-hidden="true"><span><b>O</b>D</span><span><b>O</b>S</span></span>
      {!compact && <small aria-hidden="true">ONTOLOGY-DRIVEN<br />OPERATING SYSTEM</small>}
    </span>
  );
}
