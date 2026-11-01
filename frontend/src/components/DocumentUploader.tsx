/** Drag-and-drop uploader with per-file progress and error states. */

import { useCallback, useRef, useState } from "react";

import { ACCEPTED_EXTENSIONS } from "../api/client";
import type { UploadJob } from "../hooks/useDocuments";

const ACCEPT_ATTR = ACCEPTED_EXTENSIONS.join(",");

export function DocumentUploader({
  onFiles,
}: {
  onFiles: (files: File[]) => void;
}) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const acceptFiles = useCallback(
    (list: FileList | null) => {
      if (!list || list.length === 0) {
        return;
      }
      onFiles(Array.from(list));
      if (inputRef.current) {
        inputRef.current.value = ""; // allow re-selecting the same file
      }
    },
    [onFiles],
  );

  return (
    <div
      className={`dropzone${dragOver ? " dropzone--over" : ""}`}
      role="button"
      tabIndex={0}
      aria-label="Upload documents"
      onClick={() => inputRef.current?.click()}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(event) => {
        event.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(event) => {
        event.preventDefault();
        setDragOver(false);
        acceptFiles(event.dataTransfer.files);
      }}
      data-testid="dropzone"
    >
      <span className="dropzone__hint">Drop documents here, or click to browse</span>
      <span className="dropzone__types">PDF · TXT · MD · DOCX — up to 20 MB each</span>
      <input
        ref={inputRef}
        type="file"
        className="dropzone__input"
        multiple
        accept={ACCEPT_ATTR}
        onChange={(event) => acceptFiles(event.target.files)}
      />
    </div>
  );
}

export function UploadJobsList({
  jobs,
  onDismiss,
}: {
  jobs: UploadJob[];
  onDismiss: (jobId: string) => void;
}) {
  if (jobs.length === 0) {
    return null;
  }
  return (
    <ul className="upload-jobs" data-testid="upload-jobs">
      {jobs.map((job) => (
        <li
          key={job.id}
          className={`upload-job${job.error ? " upload-job--error" : ""}`}
        >
          <span className="upload-job__name">{job.fileName}</span>
          {job.error ? (
            <span className="upload-job__errorrow">
              <span className="upload-job__error" role="alert">
                {job.error}
              </span>
              <button
                type="button"
                className="upload-job__dismiss"
                aria-label={`Dismiss ${job.fileName}`}
                onClick={() => onDismiss(job.id)}
              >
                ×
              </button>
            </span>
          ) : (
            <span
              className="upload-job__bar"
              aria-label={`Uploading ${job.fileName}: ${job.percent}%`}
            >
              <span
                className="upload-job__bar-fill"
                style={{ width: `${job.done ? 100 : job.percent}%` }}
              />
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}