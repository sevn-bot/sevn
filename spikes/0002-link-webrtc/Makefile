# Spike S1 local tasks. From the repo root:
#   make -C spikes/0002-link-webrtc test
# RUN_MARKED=1 runs ignored Rust tests (still skips ignore = "live")
# and sets SEVN_RUN_MARKED=1 for the harness.

.PHONY: build test measure spike-build spike-test spike-measure

build: spike-build
test: spike-test
measure: spike-measure

spike-build:
	cargo build --workspace

ifeq ($(RUN_MARKED),1)
spike-test:
	cargo test --workspace -- --include-ignored --skip live
	cd harness && SEVN_RUN_MARKED=1 pnpm test
else
spike-test:
	cargo test --workspace
	cd harness && pnpm test
endif

spike-measure:
	@echo "spike-measure: no scenarios until W3"
