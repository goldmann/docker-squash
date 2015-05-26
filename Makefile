test: clean
	CIRCLE_TEST_REPORTS=. tox

test-py27: clean
	CIRCLE_TEST_REPORTS=. tox -e py27

test-py34: clean
	CIRCLE_TEST_REPORTS=. tox -e py34

clean:
	@find . -name "*.pyc" -exec rm -rf {} \;

release: test
	python setup.py clean
	python setup.py register
	python setup.py sdist
	python setup.py sdist upload
