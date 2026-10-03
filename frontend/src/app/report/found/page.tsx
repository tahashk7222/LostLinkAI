"use client";

import { Protected, PageHeader } from "@/components/ui";
import { ReportForm } from "@/components/ReportForm";

export default function ReportFoundPage() {
  return (
    <Protected>
      <div className="mx-auto max-w-3xl">
        <PageHeader title="Report a found item" subtitle="Thank you for helping! Your contact details are never shared." />
        <ReportForm type="FOUND" />
      </div>
    </Protected>
  );
}
