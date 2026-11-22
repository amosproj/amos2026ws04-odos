declare module "virtual:legal-notices" {
  import type { LicenseManifest } from "./legal/manifest";
  const manifest: LicenseManifest;
  export default manifest;
}
