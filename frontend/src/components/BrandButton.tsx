import { Logo } from "./Logo";

/** The ODOS branding (logo and "ONTOLOGY-DRIVEN OPERATING SYSTEM") as one button that leads to the document workspace. */
export function BrandButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="brand-btn" onClick={onClick} aria-label="ODOS home" title="Back to the document workspace">
      <Logo />
    </button>
  );
}
