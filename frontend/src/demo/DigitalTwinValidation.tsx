import { useRef, useState } from "react";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import "./digital-twin-validation.css";

/** UI preview only. No file contents, model requests or validation API calls. */
export function DigitalTwinValidation({ documentName, ruleSourceName, onBack }: { documentName: string; ruleSourceName?: string; onBack: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const ruleInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [ruleFile, setRuleFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ruleError, setRuleError] = useState<string | null>(null);
  const [demonstrated, setDemonstrated] = useState(false);

  const choose = (next: File | undefined) => {
    if (!next) return;
    setDemonstrated(false); setError(null);
    if (!/\.json$/i.test(next.name)) {
      setFile(null); setError("Choose a JSON file.");
      if (input.current) input.current.value = "";
      return;
    }
    setFile(next);
  };
  const chooseRules = (next: File | undefined) => {
    if (!next) return;
    setDemonstrated(false); setRuleError(null);
    if (!/\.json$/i.test(next.name)) {
      setRuleError("Choose a JSON file for the rule source.");
      if (ruleInput.current) ruleInput.current.value = "";
      return;
    }
    setRuleFile(next);
  };
  const extractedRules = () => {
    setRuleFile(null); setRuleError(null); setDemonstrated(false);
    if (ruleInput.current) ruleInput.current.value = "";
  };
  const clear = () => {
    setFile(null); setError(null); setDemonstrated(false);
    if (input.current) input.current.value = "";
  };

  return (
    <main className="workspace twin-validation">
      <header className="docbar">
        <Logo compact />
        <span className="docbar-sep" aria-hidden="true" />
        <h2>Digital Twin Validation</h2>
        <span className="demo-status">Preview</span>
        <span className="spacer" />
        <button className="btn" type="button" onClick={onBack}><Icon name="back" size={16} />Back to rule extraction</button>
      </header>
      <div className="twin-body">
        <h1>Validate your digital twin</h1>
        <p className="muted">Choose your digital twin data and Rule JSON source.</p>
        <section className="twin-card" aria-labelledby="twin-upload-heading">
          <div className="twin-source">
            <Icon name="file" size={18} />
            <span>Rule source: <strong>{ruleFile ? ruleFile.name : ruleSourceName ?? documentName}</strong>
              {!ruleFile && <small>Extracted Rule JSON</small>}
            </span>
            <div className="twin-source-actions">
              <button className="btn small" type="button" aria-describedby="rule-source-help" onClick={() => ruleInput.current?.click()}>Upload Rule JSON</button>
              {(ruleFile || ruleError) && <button className="btn small" type="button" onClick={extractedRules}>Use extracted rules</button>}
            </div>
          </div>
          <p className="muted" id="rule-source-help">Use the extracted rules, or upload Rule JSON from another legal document.</p>
          <input ref={ruleInput} id="rule-source-file" type="file" accept=".json,application/json" hidden
                 aria-label="Upload Rule JSON source" onChange={event => chooseRules(event.target.files?.[0])} />
          {ruleError && <p className="alert error" role="alert">{ruleError}</p>}
          <h2 id="twin-upload-heading">Digital twin data</h2>
          <div className="twin-upload" role="button" tabIndex={0} aria-label="Choose digital twin JSON file"
               onClick={() => input.current?.click()}
               onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); input.current?.click(); } }}
               onDragOver={event => event.preventDefault()}
               onDrop={event => { event.preventDefault(); choose(event.dataTransfer.files?.[0]); }}>
            <Icon name="upload" size={28} />
            <strong>Drop a JSON file here or click to choose</strong>
            <span>JSON</span>
          </div>
          <input ref={input} id="digital-twin-file" type="file" accept=".json,application/json" hidden
                 aria-label="Digital twin JSON file" onChange={event => choose(event.target.files?.[0])} />
          {file && <div className="twin-file" role="status">
            <Icon name="file" size={18} />
            <span><strong>{file.name}</strong><small>{Math.max(1, Math.round(file.size / 1024)).toLocaleString()} KB · selected locally</small></span>
            <button className="btn small" type="button" onClick={clear}>Remove file</button>
          </div>}
          {error && <p className="alert error" role="alert">{error}</p>}
          <div className="twin-actions">
            <button className="btn primary" type="button" disabled={!file || !!ruleError} onClick={() => setDemonstrated(true)}>Validate</button>
          </div>
          <p className="twin-note"><Icon name="info" size={16} /><span>Validation is not connected yet.</span></p>
          {demonstrated && <div className="twin-demo-result" role="status">
            <strong>Validation preview</strong>
            <p>This is where the results for {file?.name} using {ruleFile ? ruleFile.name : "the extracted rules"} will appear once validation is implemented. No rules or file contents have been checked.</p>
          </div>}
        </section>
      </div>
    </main>
  );
}
