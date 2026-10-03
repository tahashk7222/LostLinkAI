"use client";

import { Protected, PageHeader } from "@/components/ui";
import { ReportForm } from "@/components/ReportForm";

export default function ReportLostPage() {
  return (
    <Protected>
      <div className="mx-auto max-w-3xl">
        <PageHeader title="Report a lost item" subtitle="Takes about a minute. LostLink AI will start looking for matches right away." />
        <ReportForm type="LOST" />
      </div>
    </Protected>
  );
}
