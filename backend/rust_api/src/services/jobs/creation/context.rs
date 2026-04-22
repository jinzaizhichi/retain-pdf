use std::collections::HashSet;
use std::path::Path;
use std::sync::Arc;

use tokio::sync::Mutex;
use tokio::sync::RwLock;

use crate::config::AppConfig;
use crate::db::Db;
use crate::services::job_factory::{build_job_launch_deps, JobLaunchDeps};
use crate::AppState;

#[derive(Clone)]
pub(crate) struct CreationDeps<'a> {
    pub(crate) db: &'a Db,
    pub(crate) config: &'a AppConfig,
    pub(crate) launcher: JobLaunchDeps<'a>,
}

impl<'a> CreationDeps<'a> {
    pub(crate) fn from_state(state: &'a AppState) -> Self {
        Self {
            db: state.db.as_ref(),
            config: state.config.as_ref(),
            launcher: build_job_launch_deps(state),
        }
    }
}

#[derive(Clone)]
pub(crate) struct BundleBuildDeps<'a> {
    pub(crate) creation: CreationDeps<'a>,
    pub(crate) downloads_lock: &'a Arc<Mutex<()>>,
}

impl<'a> BundleBuildDeps<'a> {}

#[derive(Clone)]
pub(crate) struct ControlDeps<'a> {
    pub(crate) db: &'a Db,
    pub(crate) data_root: &'a Path,
    pub(crate) output_root: &'a Path,
    pub(crate) canceled_jobs: &'a RwLock<HashSet<String>>,
}

impl<'a> ControlDeps<'a> {
    pub(crate) fn from_state(state: &'a AppState) -> Self {
        Self {
            db: state.db.as_ref(),
            data_root: &state.config.data_root,
            output_root: &state.config.output_root,
            canceled_jobs: &state.canceled_jobs,
        }
    }
}

#[derive(Clone)]
pub(crate) struct ReplayDeps<'a> {
    pub(crate) config: &'a AppConfig,
    pub(crate) data_root: &'a Path,
}

impl<'a> ReplayDeps<'a> {
    pub(crate) fn from_state(state: &'a AppState) -> Self {
        Self {
            config: state.config.as_ref(),
            data_root: &state.config.data_root,
        }
    }
}

#[derive(Clone)]
pub(crate) struct QueryJobsDeps<'a> {
    pub(crate) db: &'a Db,
    pub(crate) config: &'a AppConfig,
    pub(crate) downloads_lock: &'a Arc<Mutex<()>>,
    pub(crate) replay: ReplayDeps<'a>,
}

impl<'a> QueryJobsDeps<'a> {
    pub(crate) fn from_state(state: &'a AppState) -> Self {
        Self {
            db: state.db.as_ref(),
            config: state.config.as_ref(),
            downloads_lock: &state.downloads_lock,
            replay: ReplayDeps::from_state(state),
        }
    }
}

#[derive(Clone)]
pub(crate) struct CommandJobsDeps<'a> {
    pub(crate) db: &'a Db,
    pub(crate) creation: CreationDeps<'a>,
    pub(crate) downloads_lock: &'a Arc<Mutex<()>>,
    pub(crate) control: ControlDeps<'a>,
}

impl<'a> CommandJobsDeps<'a> {
    pub(crate) fn from_state(state: &'a AppState) -> Self {
        Self {
            db: state.db.as_ref(),
            creation: CreationDeps::from_state(state),
            downloads_lock: &state.downloads_lock,
            control: ControlDeps::from_state(state),
        }
    }
}
