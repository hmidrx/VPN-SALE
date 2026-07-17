import { previewPrice } from "./api";
import type { PricePreview, QuoteSelection } from "./types";
export class PreviewController { private abort?: AbortController; private seq = 0; async request(selection: QuoteSelection): Promise<PricePreview> { this.abort?.abort(); const local = ++this.seq; this.abort = new AbortController(); const result = await previewPrice(selection, this.abort.signal); if (local !== this.seq) throw new Error("stale_preview"); return result; } cancel(): void { this.abort?.abort(); } }
