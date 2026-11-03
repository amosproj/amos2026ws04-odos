import type { DocumentModel } from "../types";
import type { LiveData } from "./live";

export interface DemoResult {
  title: string;
  model: DocumentModel;
  json: string;
  download: {
    href: string;
    name: string;
  };
  live?: LiveData;
}