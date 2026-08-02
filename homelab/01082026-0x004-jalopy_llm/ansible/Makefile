.DEFAULT_GOAL := help
SHELL := /bin/bash

PLAYBOOK ?= site.yml
LIMIT    ?= aihost
TAGS     ?=
EXTRA    ?=

ANSIBLE_ARGS = --limit $(LIMIT) $(if $(TAGS),--tags $(TAGS),) $(EXTRA)

.PHONY: help deps lint test syntax check apply verify bench facts clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Variables: LIMIT=$(LIMIT) TAGS=$(TAGS) PLAYBOOK=$(PLAYBOOK)"
	@echo ""
	@echo "  Run one phase:      make apply TAGS=phase4"
	@echo "  Dry run everything: make check"
	@echo "  Destructive opts:   make apply TAGS=storage EXTRA='-e aihost_allow_zpool_create=true'"

deps: ## Install required Ansible collections into .collections/
	ansible-galaxy collection install -r requirements.yml -p .collections

lint: ## yamllint + ansible-lint
	@command -v yamllint >/dev/null     || { echo "pip install yamllint"; exit 1; }
	@command -v ansible-lint >/dev/null || { echo "pip install ansible-lint"; exit 1; }
	yamllint .
	ansible-lint

test: ## Run the offline tests (no host needed)
	ansible-playbook tests/parsing.yml
	ansible-playbook tests/templates.yml

syntax: ## Parse the playbooks without touching a host
	ansible-playbook $(PLAYBOOK) --syntax-check
	ansible-playbook verify.yml --syntax-check
	ansible-playbook tests/parsing.yml --syntax-check
	ansible-playbook tests/templates.yml --syntax-check

check: ## Dry run against the real host (--check --diff)
	ansible-playbook $(PLAYBOOK) --check --diff $(ANSIBLE_ARGS)

apply: ## Converge the host
	ansible-playbook $(PLAYBOOK) $(ANSIBLE_ARGS)

verify: ## Run the post-install verification playbook only
	ansible-playbook verify.yml --limit $(LIMIT) $(EXTRA)

# Pass multi-word values as JSON: Ansible splits `-e key=value` on whitespace,
# so -e 'x=--n-cpu-moe 40' silently drops the 40.
#   make bench EXTRA='-e {"llama_cpp_bench_model":"/path.gguf","llama_cpp_bench_extra":"--n-cpu-moe 40"}'
bench: ## Re-run the llama-bench baseline (see the note above for passing args)
	ansible-playbook $(PLAYBOOK) --tags bench $(ANSIBLE_ARGS)

facts: ## Dump the gathered facts for the host
	ansible $(LIMIT) -m ansible.builtin.setup

clean: ## Drop the local fact cache
	rm -rf .facts_cache
