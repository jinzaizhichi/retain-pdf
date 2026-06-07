import test from "node:test";
import assert from "node:assert/strict";

import { isNewerVersion } from "../src/js/features/app-update/github-release.js";
import {
  readUpdateCache,
  writeUpdateCache,
} from "../src/js/features/app-update/state.js";

function withLocalStorage(fn) {
  const store = new Map();
  const previousWindow = globalThis.window;
  globalThis.window = {
    localStorage: {
      getItem: (key) => store.get(key) || null,
      setItem: (key, value) => store.set(key, value),
    },
  };
  try {
    return fn();
  } finally {
    globalThis.window = previousWindow;
  }
}

test("isNewerVersion compares beta suffix numbers instead of only major version", () => {
  assert.equal(isNewerVersion("v4.1.6-beta2", "4.1.6-beta1"), true);
  assert.equal(isNewerVersion("v4.1.6-beta1", "4.1.6-beta2"), false);
  assert.equal(isNewerVersion("v4.1.7", "4.1.6-beta9"), true);
});

test("update cache reports freshness using 24 hour ttl", () => {
  withLocalStorage(() => {
    writeUpdateCache({
      currentVersion: "4.1.6-beta1",
      latestVersion: "4.1.6-beta2",
      hasUpdate: true,
      htmlUrl: "https://github.com/wxyhgk/retain-pdf/releases/tag/v4.1.6-beta2",
    }, 1000);

    const fresh = readUpdateCache(1000 + 23 * 60 * 60 * 1000);
    assert.equal(fresh.fresh, true);
    assert.equal(fresh.info.hasUpdate, true);

    const stale = readUpdateCache(1000 + 25 * 60 * 60 * 1000);
    assert.equal(stale.fresh, false);
    assert.equal(stale.info.latestVersion, "4.1.6-beta2");
  });
});
