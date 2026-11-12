import type { DocumentModel } from "../types";
import type { LiveData } from "./live";

export interface DemoResult {
  title: string;
  /** The uploaded file's name, for the result view's header. */
  filename?: string;
  model: DocumentModel;
  json: string;
  download: {
    href: string;
    name: string;
  };
  live?: LiveData;
}