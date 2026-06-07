import test from "node:test";
import assert from "node:assert/strict";

import { normalizeJobPayload } from "../src/js/job-normalize.js";
import {
  collectStageProgressByKey,
  resolveDisplayedStagePresentation,
} from "../src/js/job-stage-presentation.js";
import { summarizeStageProgressText } from "../src/js/job-status-summary-progress.js";
import { recentJobRawImageUrls } from "../src/js/features/recent-jobs/card-presenter.js";

test("normalizeJobPayload completes progress for succeeded jobs", () => {
  const job = normalizeJobPayload({
    code: 0,
    data: {
      job_id: "job-1",
      status: "succeeded",
      progress: {
        current: 2,
        total: 8,
        percent: 25,
      },
    },
  });

  assert.equal(job.progress_current, 8);
  assert.equal(job.progress_total, 8);
  assert.equal(job.progress_percent, 100);
});

test("summarizeStageProgressText formats stable user-facing progress copy", () => {
  assert.equal(
    summarizeStageProgressText({
      status: "running",
      current_stage: "translation_batches",
      progress_current: 2,
      progress_total: 5,
      progress_unit: "batch",
    }),
    "第 2/5 批",
  );

  assert.equal(
    summarizeStageProgressText({
      status: "running",
      current_stage: "compile",
      substage: "render_compile",
      progress_current: 1,
      progress_total: 2,
      progress_unit: "step",
    }),
    "编译 1/2",
  );

  assert.equal(
    summarizeStageProgressText({
      status: "running",
      current_stage: "rendering",
      substage: "render_prewarm",
      progress_current: 1,
      progress_total: 4,
      progress_unit: "step",
    }),
    "预热 1/4",
  );
});

test("resolveDisplayedStagePresentation exposes composite render compile progress", () => {
  const job = {
    job_id: "job-render",
    workflow: "book",
    status: "running",
    current_stage: "rendering",
    progress_current: 0,
    progress_total: 100,
  };
  const eventsPayload = {
    items: [
      {
        seq: 1,
        event_type: "stage_progress",
        stage: "render_prepare",
        substage: "render_prepare",
        progress_current: 1,
        progress_total: 2,
        progress_unit: "step",
      },
      {
        seq: 2,
        event_type: "stage_progress",
        stage: "rendering",
        substage: "render_pages",
        progress_current: 5,
        progress_total: 10,
        progress_unit: "page",
      },
      {
        seq: 3,
        event_type: "stage_progress",
        stage: "compile",
        substage: "render_compile",
        progress_current: 1,
        progress_total: 2,
        progress_unit: "step",
      },
    ],
  };

  const presentation = resolveDisplayedStagePresentation(job, eventsPayload);

  assert.equal(presentation.stageKey, "render");
  assert.equal(presentation.progressCurrent, 90);
  assert.equal(presentation.progressTotal, 100);
  assert.equal(presentation.progressUnit, "percent");
  assert.equal(presentation.progressText, "编译 1/2");
});

test("resolveDisplayedStagePresentation preserves composite render prewarm progress text", () => {
  const presentation = resolveDisplayedStagePresentation(
    {
      job_id: "job-prewarm",
      workflow: "book",
      status: "running",
      current_stage: "rendering",
    },
    {
      items: [
        {
          seq: 1,
          event_type: "stage_progress",
          stage: "rendering",
          substage: "render_prewarm",
          progress_current: 2,
          progress_total: 4,
          progress_unit: "step",
        },
      ],
    },
  );

  assert.equal(presentation.progressCurrent, 5);
  assert.equal(presentation.progressTotal, 100);
  assert.equal(presentation.progressUnit, "percent");
  assert.equal(presentation.progressText, "预热 2/4");
});

test("resolveDisplayedStagePresentation accepts structured event progress objects", () => {
  const presentation = resolveDisplayedStagePresentation(
    {
      job_id: "job-structured-progress",
      workflow: "book",
      status: "running",
      stage: "render",
      progress: {
        current: 0,
        total: 100,
        percent: 0,
        unit: "percent",
      },
    },
    {
      items: [
        {
          seq: 1,
          stage: "render",
          substage: "render_pages",
          progress: {
            unit: "page",
            current: 4,
            total: 20,
            percent: 20,
          },
        },
        {
          seq: 2,
          stage: "render",
          substage: "render_compile",
          progress: {
            unit: "step",
            current: 1,
            total: 2,
            percent: 50,
          },
        },
      ],
    },
  );

  assert.equal(presentation.stageKey, "render");
  assert.equal(presentation.progressCurrent, 90);
  assert.equal(presentation.progressTotal, 100);
  assert.equal(presentation.progressUnit, "percent");
  assert.equal(presentation.progressText, "编译 1/2");
});

test("collectStageProgressByKey keeps translation substage progress", () => {
  const progressByKey = collectStageProgressByKey(
    {
      job_id: "job-translate",
      workflow: "book",
      status: "running",
      current_stage: "translation_batches",
    },
    {
      items: [
        {
          seq: 1,
          stage: "continuation_review",
          substage: "continuation_review",
          progress_current: 2,
          progress_total: 10,
          progress_unit: "page",
        },
        {
          seq: 2,
          stage: "page_policies",
          substage: "page_policies",
          progress_current: 3,
          progress_total: 10,
          progress_unit: "page",
        },
        {
          seq: 3,
          stage: "translation_batches",
          substage: "translation_batches",
          progress_current: 4,
          progress_total: 8,
          progress_unit: "batch",
        },
      ],
    },
  );

  assert.equal(progressByKey.translate.current, 4);
  assert.equal(progressByKey.translate.total, 8);
  assert.equal(progressByKey.translate.progressText, "第 4/8 批");
  assert.equal(progressByKey.translate.bySubstage.continuation_review.current, 2);
  assert.equal(progressByKey.translate.bySubstage.page_policies.current, 3);
});

test("frontend progress uses canonical display_stage event contract", () => {
  const progressByKey = collectStageProgressByKey(
    {
      job_id: "job-new-events",
      workflow: "book",
      status: "running",
      display_stage: "translation",
      stage: "translating",
      progress: {
        unit: "batch",
        current: 1,
        total: 8,
      },
    },
    {
      items: [
        {
          seq: 1,
          display_stage: "ocr",
          stage: "ocr_processing",
          substage: "provider_processing",
          event_type: "progress",
          progress: {
            unit: "page",
            current: 12,
            total: 34,
          },
        },
        {
          seq: 2,
          display_stage: "translation",
          stage: "translating",
          substage: "translation_batches",
          event_type: "progress",
          progress: {
            unit: "batch",
            current: 4,
            total: 8,
          },
        },
        {
          seq: 3,
          display_stage: "render",
          stage: "rendering",
          substage: "render_pages",
          event_type: "progress",
          progress: {
            unit: "page",
            current: 5,
            total: 20,
          },
        },
      ],
    },
  );

  assert.equal(progressByKey.ocr.progressText, "第 12/34 页");
  assert.equal(progressByKey.translate.progressText, "第 4/8 批");
  assert.equal(progressByKey.render.progressText, "第 5/20 页");
});

test("background render events do not advance the main status card", () => {
  const job = {
    job_id: "job-parallel",
    workflow: "book",
    status: "running",
    display_stage: "translation",
    stage: "translating",
    progress: {
      unit: "batch",
      current: 120,
      total: 900,
    },
  };
  const eventsPayload = {
    items: [
      {
        seq: 1,
        lane: "main",
        display_stage: "translation",
        stage: "translating",
        substage: "translation_batches",
        event_type: "progress",
        progress: {
          unit: "batch",
          current: 120,
          total: 900,
        },
      },
      {
        seq: 2,
        lane: "background",
        display_stage: "render",
        stage: "render_preprocess",
        substage: "render_prewarm",
        event_type: "progress",
        progress: {
          unit: "step",
          current: 2,
          total: 3,
        },
      },
    ],
  };

  const presentation = resolveDisplayedStagePresentation(job, eventsPayload);
  const progressByKey = collectStageProgressByKey(job, eventsPayload);

  assert.equal(presentation.stageKey, "translate");
  assert.equal(presentation.progressText, "第 120/900 批");
  assert.equal(progressByKey.render, undefined);
});

test("recent job covers include stable fallback image endpoints", () => {
  assert.deepEqual(
    recentJobRawImageUrls({
      job_id: "job-cover",
      thumbnail_url: "",
      cover_url: "",
    }),
    [
      "/api/v1/jobs/job-cover/thumbnail",
      "/api/v1/library/books/job-cover/thumbnail",
      "/api/v1/jobs/job-cover/cover",
      "/api/v1/library/books/job-cover/cover",
    ],
  );

  assert.deepEqual(
    recentJobRawImageUrls({
      job_id: "job-cover",
      thumbnail_url: "https://example.test/api/v1/library/books/job-cover/thumbnail",
      cover_url: "https://example.test/api/v1/library/books/job-cover/cover",
    }).slice(0, 2),
    [
      "https://example.test/api/v1/library/books/job-cover/thumbnail",
      "https://example.test/api/v1/library/books/job-cover/cover",
    ],
  );
});
