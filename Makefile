CIRCLE_NODE_INDEX ?= 0

test: prepare
	tox -- tests

test-py27: prepare
	tox -e py27 -- tests

test-py34: prepare
	tox -e py34 -- tests

test-py35: prepare
	tox -e py35 -- tests

test-unit: prepare
	tox -- tests/test_unit*

test-integ: prepare
	tox -- tests/test_integ*

ci-install-docker:
ifeq ($(CIRCLE_NODE_INDEX),0)
	@echo "Installing Docker 1.10"
	@curl -sSL https://s3.amazonaws.com/circle-downloads/install-circleci-docker.sh | bash -s -- 1.10.0
else
	@echo "Installing Docker 1.9.1"
	@sudo curl -L -o /usr/bin/docker https://s3-external-1.amazonaws.com/circle-downloads/docker-1.9.1-circleci
	@sudo chmod +x /usr/bin/docker
endif

ci-publish-junit:
	@mkdir -p ${CIRCLE_TEST_REPORTS}
	@cp target/junit*.xml ${CIRCLE_TEST_REPORTS}

clean:
	@find . -name "*.pyc" -exec rm -rf {} \;
	@rm -rf target

prepare: clean
	@mkdir target

hook-gitter:
	@curl -s -X POST -H "Content-Type: application/json" -d "{\"payload\":`curl -s -H "Accept: application/json" https://circleci.com/api/v1/project/goldmann/docker-squash/${CIRCLE_BUILD_NUM}`}" ${GITTER_WEBHOOK_URL}

release: clean
	python setup.py clean
	python setup.py register
	python setup.py sdist
	python setup.py sdist upload
