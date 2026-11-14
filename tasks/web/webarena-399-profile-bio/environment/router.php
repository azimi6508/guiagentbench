<?php
// The fixed upstream test account is a fixture, not a real service credential.
$_SERVER['HTTP_X_POSTMILL_AUTO_LOGIN'] = 'MarvelsGrantMan136:test1234';
$_SERVER['SCRIPT_NAME'] = '/index.php';
$_SERVER['SCRIPT_FILENAME'] = '/var/www/html/public/index.php';
require '/var/www/html/public/index.php';
