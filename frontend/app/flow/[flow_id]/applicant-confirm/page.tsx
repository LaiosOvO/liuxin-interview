/**
 * WEB-04 申请人最终确认页 server entry
 *
 * 静态导出限制 — server component 只暴露 generateStaticParams；
 * 实际渲染交给 ./applicant-confirm-client.tsx（'use client'）。
 */

import { ApplicantConfirmClient } from './applicant-confirm-client';

export function generateStaticParams() {
  return [{ flow_id: 'placeholder' }];
}

export default function Page() {
  return <ApplicantConfirmClient />;
}
