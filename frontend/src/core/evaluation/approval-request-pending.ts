import { useSyncExternalStore } from "react";

import type { SignatureRequest, SignatureState } from "./approval-requests";

export type AssignmentPending = {
  id: string;
  projectId: string;
  runId: string;
  assessmentId: string;
  assessmentHash: string;
  approverId: string;
  expires: number;
};

export type SignaturePending = {
  kind: "view" | "approved" | "revoked" | "cancelled";
  id: string;
  source: SignatureRequest;
  state: SignatureState;
};

const assignments = new Map<string, AssignmentPending>();
const signatures = new Map<string, SignaturePending>();
const assignmentLocks = new Set<string>();
const signatureLocks = new Set<string>();
const listeners = new Set<() => void>();
let revision = 0;

function publish() {
  revision += 1;
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot() {
  return revision;
}

export function useApprovalRequestPendingRevision() {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}

export function getPendingAssignment(actor: string) {
  return assignments.get(actor);
}

export function beginAssignment(actor: string, pending: AssignmentPending) {
  if (assignmentLocks.has(actor) || assignments.has(actor)) return false;
  assignmentLocks.add(actor);
  assignments.set(actor, pending);
  publish();
  return true;
}

export function finishAssignment(actor: string, resolved: boolean) {
  assignmentLocks.delete(actor);
  if (resolved) assignments.delete(actor);
  publish();
}

export function lockAssignmentReconciliation(actor: string) {
  if (assignmentLocks.has(actor)) return false;
  assignmentLocks.add(actor);
  publish();
  return true;
}

export function unlockAssignmentReconciliation(actor: string) {
  assignmentLocks.delete(actor);
  publish();
}

export function getPendingSignature(actor: string) {
  return signatures.get(actor);
}

export function beginSignature(actor: string, pending: SignaturePending) {
  if (signatureLocks.has(actor) || signatures.has(actor)) return false;
  signatureLocks.add(actor);
  signatures.set(actor, pending);
  publish();
  return true;
}

export function finishSignature(actor: string, resolved: boolean) {
  signatureLocks.delete(actor);
  if (resolved) signatures.delete(actor);
  publish();
}

export function lockSignatureReconciliation(actor: string) {
  if (signatureLocks.has(actor)) return false;
  signatureLocks.add(actor);
  publish();
  return true;
}

export function unlockSignatureReconciliation(actor: string) {
  signatureLocks.delete(actor);
  publish();
}

export function lockSignatureRead(actor: string) {
  if (signatureLocks.has(actor) || signatures.has(actor)) return false;
  signatureLocks.add(actor);
  publish();
  return true;
}

export function unlockSignatureRead(actor: string) {
  signatureLocks.delete(actor);
  publish();
}
