.PHONY: validate validate-spec test package pull download push clean

PYTHON ?= python3
MAVEN ?= mvn

validate:
	$(PYTHON) scripts/validate_blueprint.py
	$(PYTHON) scripts/validate_modular.py
	$(PYTHON) scripts/validate_capture.py

validate-spec:
	@test -n "$(SPEC)" || { echo "SPEC is required, for example: make validate-spec SPEC=/path/to/vcf-deployment.json" >&2; exit 2; }
	$(PYTHON) scripts/validate_vcf_spec.py "$(SPEC)" $(if $(filter true,$(ALLOW_SECRET_REFERENCES)),--allow-secret-references,)

test: validate
	$(PYTHON) -m unittest discover -s tests -v

package: test
	$(MAVEN) clean package

pull:
	@test -n "$(PROFILE)" || { echo "PROFILE is required, for example: make pull PROFILE=lab" >&2; exit 2; }
	@if [ "$(FORCE)" != "true" ] && [ -n "$$(git status --porcelain)" ]; then \
		echo "Refusing to overwrite a dirty checkout; commit/stash changes or rerun with FORCE=true" >&2; \
		exit 2; \
	fi
	$(MAVEN) vcfa-all-apps:pull -P$(PROFILE)
	$(PYTHON) scripts/validate_blueprint.py
	$(PYTHON) scripts/validate_modular.py
	$(PYTHON) scripts/validate_capture.py

download: pull

push: test
	@test -n "$(PROFILE)" || { echo "PROFILE is required, for example: make push PROFILE=lab" >&2; exit 2; }
	$(MAVEN) clean package vrealize:push -P$(PROFILE)

clean:
	$(MAVEN) clean
