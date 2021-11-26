CIRCLE_NODE_INDEX ?= 0

test: prepare
	tox -- tests

test-py27: prepare
	tox -e py27 -- tests

test-py35: prepare
	tox -e py35 -- tests

test-py36: prepare
	tox -e py36 -- tests

test-py37: prepare
	tox -e py37 -- tests

test-py311: prepare
	tox -e py311 -- tests

test-unit: prepare
	tox -- tests/test_unit*

test-integ: prepare
	tox -- tests/test_integ*

ci-publish-junit:
	@mkdir -p ${CIRCLE_TEST_REPORTS}
	@cp target/junit*.xml ${CIRCLE_TEST_REPORTS}

clean:
	@find . -name "*.pyc" -exec rm -rf {} \;
	@rm -rf target
	@rm -rf dist

prepare: clean
	@mkdir target

hook-gitter:
	@curl -s -X POST -H "Content-Type: application/json" -d "{\"payload\":`curl -s -H "Accept: application/json" https://circleci.com/api/v1/project/goldmann/docker-squash/${CIRCLE_BUILD_NUM}`}" ${GITTER_WEBHOOK_URL}

release: clean
	python setup.py sdist
	twine check dist/*
	twine upload dist/*
	
	
