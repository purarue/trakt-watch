# trakt-watch

A small CLI to mark items watched on trakt. This lets you:

- Mark movies/episodes as watched (by searching, providing the URL, or choosing a recent TV show to mark the next episode as watched)
- Rate movies/episodes
- Remove recently watched items from your history
- Query your recent history

This uses [traktexport](https://github.com/purarue/traktexport) internally to authenticate, so follow the steps [here](https://github.com/purarue/traktexport#auth) to login/setup your credentials.

## Installation

Requires `python3.11+`

To install with pip, run:

```
pip install trakt-watch
```

## Usage

You can set the `TRAKT_USERNAME` environment variable so you don't have to pass it every time.

```
Usage: trakt-watch [OPTIONS] COMMAND [ARGS]...

Options:
  -u, --username TEXT  Trakt username  [env var: TRAKT_USERNAME; required]
  -h, --help           Show this message and exit.

Commands:
  progress  mark next episode in progress
  rate      rate movie/tv show/episode
  recent    show recent history
  unwatch   remove recent watched item
  watch     mark movie/episode as watched
```

To watch entries, you can provide a URL, or search for a movie/TV show/episode. By default, will use now as the watched time:

```
Usage: trakt-watch watch [OPTIONS]

  Mark an entry on trakt.tv as watched

Options:
  --url URL                   URL to watch
  -a, --at DATE               Watched at time (date like string, or 'released')
  -r, --rating INTEGER RANGE  Rating  [1<=x<=10]
  -l, --letterboxd            open corresponding letterboxd.com entry in your browser
  -h, --help                  Show this message and exit.
```

Query recent history:

```
$ trakt-watch recent
2023-10-21 22:24:59 Stuff Made Here S2023E1 - I sent robot forgeries to a handwriting expert
2023-10-21 22:18:10 Possession
2023-10-21 19:33:15 Stuff Made Here S2023E2 - I made 6 absurd pencil sharpeners
2023-10-20 14:30:00 Killers of the Flower Moon
2023-10-18 23:49:06 RWBY S9E10 - Of Solitude and Self
2023-10-18 17:28:11 RWBY S9E9 - A Tale Involving a Tree
2023-10-17 18:32:29 RWBY S9E8 - Tea Amidst Terrible Trouble
2023-10-17 17:51:30 RWBY S9E7 - The Perils of Paper Houses
2023-10-15 22:39:51 The Wicker Man
2023-10-15 18:54:01 How to Blow Up a Pipeline
```

Set a movie as watched/rate it:

```
$ trakt-watch watch --at '10m ago' --url https://trakt.tv/movies/possession-1981
Added count:
Movies: 1

Set rating? [Y/n]:
Rating: 9
Added count:
Movies: 1

Recent history:
1: 2023-10-31 11:35:28 Possession
```

Search for an TV show and provide a season/episode number:

```
$ trakt-watch watch
[M]ovie
[S]how
[E]pisode name
Ep[I]sode - Show w/ Season/Episode num
[U]rl
[A]ll
What type of media do you want to search for?
Search for show: barry
Results:
1: Show:	'Barry (2018)' | shows/122709
2: Show:	'Carrie and Barry (2004)' | shows/9085
3: Show:	'Red Barry (1938)' | shows/128828
4: Show:	'Barry Hilton (1999)' | shows/110779
5: Show:	'Carrie & Barrie (2004)' | shows/128392
6: Show:	'Barry Tales (2013)' | shows/100038
7: Show:	'Todd Barry (2012)' | shows/105417
8: Show:	'Barry Manilow Specials (1977)' | shows/67327
9: Show:	'Barry Welsh is Coming (1996)' | shows/13243
10: Show:	'Britains Greatest Machines With Chris Barrie (2009)' | shows/49775
11: Show:	'Deception With Keith Barry (2010)' | shows/63137
'Pick result - enter 1-11, or q to quit [1]':
Season: 1
Episode: 8
```

The `progress` command works similarly to `watch`, but it presents you with a list of recently watched episodes, querying trakt for the 'next episode' like on the progress page on the trakt website.

### letterboxd

The `letterboxd` command can be used to search for a trakt entry, and then open the corresponding letterboxd URL using the TMDB ID. This is useful since letterboxd doesn't have an API, so we can use trakt's as a stand-in. I put this shell function in my shell startup:

```bash
lb () {
        trakt-watch letterboxd --action open "$@"
}
```

### Tests

```bash
git clone 'https://github.com/purarue/trakt-watch'
cd ./trakt_watch
pip install '.[testing]'
pytest
flake8 ./trakt_watch
mypy ./trakt_watch
```
