/** Document library state: list, upload queue (with progress), delete. */

import { useCallback, useState } from "react";

import {
  deleteDocument,
  describeError,
  fetchDocuments,
  uploadDocument,
  validateFile,
} from "../api/client";
import type { DocumentMeta } from "../types";

export interface UploadJob {
  id: string;
  fileName: string;
  percent: number;
  error: string | null;
  done: boolean;
}

let jobCounter = 0;
function nextJobId(fileName: string): string {
  jobCounter += 1;
  return `u${jobCounter}-${fileName}`;
}

const INITIAL_JOB: Pick<UploadJob, "percent" | "error" | "done"> = {
  percent: 0,
  error: null,
  done: false,
};

export function useDocuments() {
  const [documents, setDocuments] = useState<DocumentMeta[] | null>(null); // null = initial load
  const [uploads, setUploads] = useState<UploadJob[]>([]);
  const [deletingIds, setDeletingIds] = useState<ReadonlySet<string>>(new Set());

  const load = useCallback(async () => {
    try {
      setDocuments(await fetchDocuments());
    } catch {
      setDocuments([]);
    }
  }, []);

  const upload = useCallback(async (file: File) => {
    const jobId = nextJobId(file.name);
    const names = new Set((await safeList()).map((doc) => doc.original_name));
    const validationError = validateFile(file, names);
    if (validationError) {
      setUploads((prev) => [
        ...prev,
        { id: jobId, fileName: file.name, ...INITIAL_JOB, error: validationError, done: true },
      ]);
      return;
    }

    setUploads((prev) => [...prev, { id: jobId, fileName: file.name, ...INITIAL_JOB }]);
    try {
      const created = await uploadDocument(file, (percent) => {
        setUploads((prev) =>
          prev.map((job) => (job.id === jobId ? { ...job, percent } : job)),
        );
      });
      setUploads((prev) =>
        prev.map((job) =>
          job.id === jobId ? { ...job, percent: 100, done: true } : job,
        ),
      );
      setDocuments((prev) => (prev ? [created, ...prev] : [created]));
    } catch (error: unknown) {
      setUploads((prev) =>
        prev.map((job) =>
          job.id === jobId ? { ...job, error: describeError(error), done: true } : job,
        ),
      );
    }
  }, []);

  const uploadMany = useCallback(
    async (files: File[]) => {
      // sequential so progress lines stay readable
      for (const file of files) {
        await upload(file);
      }
    },
    [upload],
  );

  const removeUploadJob = useCallback((jobId: string) => {
    setUploads((prev) => prev.filter((job) => job.id !== jobId));
  }, []);

  const remove = useCallback(async (id: string) => {
    setDeletingIds((prev) => new Set(prev).add(id));
    try {
      await deleteDocument(id);
      setDocuments((prev) => (prev ? prev.filter((doc) => doc.id !== id) : prev));
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }, []);

  async function safeList(): Promise<DocumentMeta[]> {
    try {
      return (await fetchDocuments()) ?? [];
    } catch {
      return [];
    }
  }

  return { documents, uploads, deletingIds, load, uploadMany, removeUploadJob, remove };
}