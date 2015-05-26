test: clean
	CIRCLE_TEST_REPORTS=. tox

clean:
	@find . -name "*.pyc" -exec rm -rf {} \;

release: test
	python setup.py clean
	python setup.py register
	python setup.py sdist
	python setup.py sdist upload
