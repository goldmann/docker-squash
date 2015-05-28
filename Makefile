test: prepare
	tox -- tests

test-unit: prepare
	tox -- tests/test_unit*

test-integ: prepare
	tox -- tests/test_integ*

clean:
	@find . -name "*.pyc" -exec rm -rf {} \;
	@rm -rf target

prepare: clean
	@mkdir target

release: clean
	python setup.py clean
	python setup.py register
	python setup.py sdist
	python setup.py sdist upload
