release:
	rm hiku/console/assets/*.js
	pi build static
	python setup.py sdist
