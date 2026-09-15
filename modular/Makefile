.PHONY: validate test package push pull download clean
PYTHON ?= python3
MAVEN ?= mvn
MAVEN_FLAGS ?= --batch-mode --no-transfer-progress

validate:
	$(PYTHON) scripts/validate_modular.py

test: validate
	$(PYTHON) -m unittest discover -s tests -v

package: test
	$(MAVEN) $(MAVEN_FLAGS) clean package

push: test
	@test -n "$(PROFILE)" || { echo "PROFILE is required, for example: make push PROFILE=lab" >&2; exit 2; }
	$(MAVEN) $(MAVEN_FLAGS) clean package vrealize:push -P$(PROFILE)

pull:
	@test -n "$(PROFILE)" || { echo "PROFILE is required" >&2; exit 2; }
	@if [ "$(FORCE)" != "true" ] && [ -n "$$(git status --porcelain)" ]; then \
		echo "Commit or stash component changes before pull, or explicitly set FORCE=true" >&2; exit 2; \
	fi
	$(MAVEN) $(MAVEN_FLAGS) vcfa-all-apps:pull -P$(PROFILE)
	$(PYTHON) scripts/validate_modular.py

download: pull

clean:
	$(PYTHON) scripts/validate_modular.py --clean-local
