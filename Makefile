.PHONY: validate test package push clean

PYTHON ?= python3
MAVEN ?= mvn

validate:
	$(PYTHON) scripts/validate_blueprint.py

test: validate
	$(PYTHON) -m unittest discover -s tests -v

package: test
	$(MAVEN) clean package

push: test
	@test -n "$(PROFILE)" || { echo "PROFILE is required, for example: make push PROFILE=lab" >&2; exit 2; }
	$(MAVEN) clean package vrealize:push -P$(PROFILE)

clean:
	$(MAVEN) clean
