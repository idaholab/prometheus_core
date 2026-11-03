// This file is part of Prometheus
// https://inl.gov/super-intelligence/prometheus/
//
// Copyright 2026 Battelle Energy Alliance, LLC
// All rights reserved, see NOTICE.txt for full restrictions
// https://github.com/idaholab/prometheus_core/blob/main/NOTICE.txt
//
// Licensed under the MIT License, please see LICENSE for details
// https://github.com/idaholab/prometheus_core/blob/main/LICENSE
//
// SPDX-License-Identifier: MIT

import { useState } from "react";
import { useChatType } from "@/lib/useChatType";
import { ChatTypeSelect } from "@/components/chat/ChatTypeSelect";
import { Button } from "@/components/ui/Button";

const MODELS = [
  "None",
  "gpt-oss-120B (AmSC)",
  "gpt-oss-120B (INL)",
  "GPT-5.3 Chat (OpenAI)",
  "Claude Opus 4.6 (Anthropic)",
];

const APPROVAL_TYPES = ["None", "Workflow Level", "Agent Level"];

const DEFAULT_MODEL = "None";
const DEFAULT_APPROVAL_TYPE = "None";

interface Props {
  onClose: () => void;
}

export function SettingsPanel({ onClose }: Props) {
  const [model, setModel] = useState(DEFAULT_MODEL);
  const [approvalType, setApprovalType] = useState(DEFAULT_APPROVAL_TYPE);
  const [chatType, setChatType] = useChatType();
  const [savedModel, setSavedModel] = useState(DEFAULT_MODEL);
  const [savedApprovalType, setSavedApprovalType] = useState(DEFAULT_APPROVAL_TYPE);

  const handleReset = () => {
    setModel(DEFAULT_MODEL);
    setApprovalType(DEFAULT_APPROVAL_TYPE);
  };

  const handleCancel = () => {
    setModel(savedModel);
    setApprovalType(savedApprovalType);
    onClose();
  };

  const handleConfirm = () => {
    setSavedModel(model);
    setSavedApprovalType(approvalType);
    onClose();
  };

  return (
    <div className="flex flex-col flex-1 overflow-hidden">
      <div className="flex flex-col gap-4 p-4 flex-1 overflow-y-auto">
        <h3 className="pb-2">Settings</h3>
        <div className="form-control">
          <label className="label pb-1">
            <span className="label-text">Model</span>
          </label>
          <select
            className="select select-bordered w-full"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            {MODELS.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
        <div className="form-control">
          <label className="label pb-1">
            <span className="label-text">Approval Type</span>
          </label>
          <select
            className="select select-bordered w-full"
            value={approvalType}
            onChange={(e) => setApprovalType(e.target.value)}
          >
            {APPROVAL_TYPES.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
        <div className="form-control">
          <label className="label pb-1">
            <span className="label-text">Chat Type</span>
          </label>
          <ChatTypeSelect value={chatType} onChange={setChatType} />
        </div>
      </div>
      <div className="flex justify-between gap-2 p-3 border-t border-base-300">
        <Button variant="ghost" size="sm" label="Reset" onClick={handleReset} />
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" label="Cancel" onClick={handleCancel} />
          <Button variant="primary" size="sm" label="Confirm" onClick={handleConfirm} />
        </div>
      </div>
    </div>
  );
}
