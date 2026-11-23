import type { ReactNode } from "react";
import { Icon } from "./Icon";
import { BrandButton } from "./BrandButton";

/** The header of the workflow pages (Find Rules, Review): branding on the left, the workflow steps (`children`) in the
 *  centre, then "Back to Document" and the help control (`end`) on the right. */
export function WorkflowHeader({ onHome, onBack, end, children }: { onHome: () => void; onBack?: () => void; end?: ReactNode; children?: ReactNode }) {
  return (
    <header className="rex-top">
      <BrandButton onClick={onHome} />
      <div className="rex-top-center">{children}</div>
      <div className="rex-top-end">
        {onBack && <button type="button" className="btn rex-back-btn" onClick={onBack}><Icon name="back" size={16} />Back to Document</button>}
        {end}
      </div>
    </header>
  );
}
