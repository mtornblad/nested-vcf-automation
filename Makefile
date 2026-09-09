.PHONY: validate validate-spec test package push clean

PYTHON ?= python3
MAVEN ?= mvn

validate:
	$(PYTHON) scripts/validate_blueprint.py

validate-spec:
	@test -n "$(SPEC)" || { echo "SPEC is required, for example: make validate-spec SPEC=/path/to/vcf-deployment.json" >&2; exit 2; }
	$(PYTHON) scripts/validate_vcf_spec.py "$(SPEC)" $(if $(filter true,$(ALLOW_SECRET_REFERENCES)),--allow-secret-references,)

test: validate
	$(PYTHON) -m unittest discover -s tests -v

package: test
	$(MAVEN) clean package

push: test
	@test -n "$(PROFILE)" || { echo "PROFILE is required, for example: make push PROFILE=lab" >&2; exit 2; }
	$(MAVEN) clean package vrealize:push -P$(PROFILE)

clean:
	$(MAVEN) clean
