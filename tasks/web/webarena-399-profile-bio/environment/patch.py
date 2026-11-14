"""One reviewed storage-fault hook; no other Postmill behavior is changed."""
from pathlib import Path

path = Path('/var/www/html/src/Controller/UserController.php')
text = path.read_text()
start = text.index('    public function editBiography(')
end = text.index('\n    /**', start)
method = text[start:end]
before = '            $data->updateUser($user);'
assert method.count(before) == 1
after = '''            $previousBiography = $user->getBiography();
            $data->updateUser($user);
            $benchSettings = json_decode(file_get_contents('/settings.json'), true);
            if ($benchSettings['drop_biography_save']) {
                $user->setBiography($previousBiography);
            }'''
text = text[:start] + method.replace(before, after) + text[end:]
path.write_text(text)
