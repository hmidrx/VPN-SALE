import { notFound } from "next/navigation";
import { DesignPreview } from "../../src/components/DesignPreview";
export default function Page(): React.ReactElement { if (process.env.NODE_ENV === "production" && process.env.NEXT_PUBLIC_IDENTITY_UI_PREVIEW !== "true") notFound(); return <DesignPreview />; }
