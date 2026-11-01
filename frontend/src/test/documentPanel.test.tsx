/** Tests: DocumentPanel — uploader drag&drop, library, delete confirmation. */

import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DocumentPanel } from "../components/DocumentPanel";
import type { BackendHealth } from "../hooks/useBackendHealth";
import type { DocumentMeta } from "../types";

const HEALTH: BackendHealth = { status: "online", info: null, error: null };

function doc(overrides: Partial<DocumentMeta> = {}): DocumentMeta {
  return {
    id: "d1",
    original_name: "report.pdf",
    stored_name: "stored.pdf",
    content_type: "application/pdf",
    size_bytes: 1234,
    num_chunks: 7,
    status: "ready",
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function renderPanel(props: Partial<Parameters<typeof DocumentPanel>[0]> = {}) {
  const onFiles = vi.fn();
  const onDismissJob = vi.fn();
  const onDelete = vi.fn();
  const view = render(
    <DocumentPanel
      health={HEALTH}
      documents={[doc()]}
      uploads={[]}
      deletingIds={new Set()}
      onFiles={onFiles}
      onDismissJob={onDismissJob}
      onDelete={onDelete}
      isBackendOnline={true}
      {...props}
    />,
  );
  return { view, onFiles, onDismissJob, onDelete };
}

function makeDataTransfer(files: File[]) {
  return { files, preventDefault: () => undefined };
}

describe("DocumentUploader", () => {
  it("accepts dropped files", () => {
    const { onFiles } = renderPanel();
    const dropzone = screen.getByTestId("dropzone");
    const file = new File(["x"], "notes.md");

    fireEvent.drop(dropzone, { dataTransfer: makeDataTransfer([file]) });

    expect(onFiles).toHaveBeenCalledWith([file]);
  });

  it("handles empty drops gracefully", () => {
    const { onFiles } = renderPanel();
    fireEvent.drop(screen.getByTestId("dropzone"), {
      dataTransfer: makeDataTransfer([]),
    });
    expect(onFiles).not.toHaveBeenCalled();
  });
});

describe("UploadJobsList", () => {
  it("shows per-file progress bar while uploading", () => {
    renderPanel({
      uploads: [{ id: "u1", fileName: "big.pdf", percent: 40, error: null, done: false }],
    });

    const jobs = screen.getByTestId("upload-jobs");
    expect(within(jobs).getByText("big.pdf")).toBeTruthy();
    const bar = within(jobs).getByLabelText(/big\.pdf: 40%/i) as HTMLElement;
    expect(bar.querySelector(".upload-job__bar-fill")).toBeTruthy();
  });

  it("shows a dismissible error state", () => {
    const { onDismissJob } = renderPanel({
      uploads: [{ id: "u1", fileName: "evil.exe", percent: 0, error: "Unsupported file type.", done: true }],
    });

    expect(screen.getByRole("alert")).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/Dismiss evil\.exe/));
    expect(onDismissJob).toHaveBeenCalledWith("u1");
  });
});

describe("document library", () => {
  it("lists filename, status and metadata", () => {
    renderPanel();

    expect(screen.getByText("report.pdf")).toBeTruthy();
    expect(screen.getByText(/ready/)).toBeTruthy();
    expect(screen.getByText(/7 chunks/)).toBeTruthy();
  });

  it("shows an empty-library message when there are no documents", () => {
    renderPanel({ documents: [] });
    expect(screen.getByTestId("empty-library")).toBeTruthy();
  });

  it("shows Loading… while the list is null", () => {
    renderPanel({ documents: null });
    expect(screen.getByText("Loading…")).toBeTruthy();
  });

  it("requires confirmation before deleting", async () => {
    const { onDelete } = renderPanel();

    fireEvent.click(screen.getByLabelText(/Delete report\.pdf/));
    const confirm = screen.getByTestId("delete-confirm");
    expect(confirm).toBeTruthy(); // confirmation visible
    expect(onDelete).not.toHaveBeenCalled();

    fireEvent.click(within(confirm).getByRole("button", { name: "Delete" }));

    expect(onDelete).toHaveBeenCalledWith("d1");
  });

  it("closes the dialog on cancel", () => {
    const { onDelete } = renderPanel();

    fireEvent.click(screen.getByLabelText(/Delete report\.pdf/));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByTestId("delete-confirm")).toBeNull();
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("disables delete while the row is being deleted", () => {
    renderPanel({ deletingIds: new Set(["d1"]) });
    expect((screen.getByLabelText(/Delete report\.pdf/) as HTMLButtonElement).disabled).toBe(true);
  });

  it("waits for confirmation to appear via RTL waitFor flows", async () => {
    const { onDelete } = renderPanel();
    fireEvent.click(screen.getByLabelText(/Delete report\.pdf/));
    await waitFor(() => expect(screen.getByTestId("delete-confirm")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(onDelete).toHaveBeenCalledWith("d1"));
  });
});