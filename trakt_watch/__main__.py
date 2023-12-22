#!/usr/bin/env python3

import os
import json
from typing import (
    get_args,
    assert_never,
    TypeVar,
    List,
    Literal,
    Callable,
    Optional,
    NamedTuple,
    Union,
    Iterator,
    Iterable,
    Any,
)
from datetime import datetime, timezone

import click
from logzero import logger  # type: ignore[import]

from trakt.movies import Movie  # type: ignore[import]
from trakt.tv import TVShow, TVEpisode  # type: ignore[import]
from trakt.people import Person  # type: ignore[import]
from traktexport.export import _check_config

_check_config()

USERNAME: Optional[str] = None


@click.group(
    context_settings={"help_option_names": ["-h", "--help"], "max_content_width": 120}
)
@click.option(
    "-u",
    "--username",
    help="Trakt username",
    required=True,
    envvar="TRAKT_USERNAME",
    show_envvar=True,
)
def main(username: str) -> None:
    global USERNAME

    USERNAME = username


class MovieId(NamedTuple):
    id: str

    def trakt(self) -> Movie:
        from trakt.movies import Movie

        mv = Movie(self.id, year=None, slug=self.id)
        mv._get()
        return mv


class EpisodeId(NamedTuple):
    id: str
    season: int
    episode: int

    def trakt(self) -> TVEpisode:
        from trakt.tv import TVEpisode

        ep = TVEpisode(show=self.id, season=self.season, number=self.episode)
        ep._get()
        return ep


class TVShowId(NamedTuple):
    id: str

    def trakt(self) -> TVShow:
        from trakt.tv import TVShow

        tv = TVShow(self.id)
        tv._get()
        return tv


Input = Union[MovieId, EpisodeId, TVShowId]


def _print_response_pretty(d: Any, rating: bool = False) -> bool:
    if not isinstance(d, dict):
        return False
    try:
        if "added" in d or "deleted" in d:
            key = "added" if "added" in d else "deleted"
            if d[key]["movies"] or d[key]["episodes"]:
                print_text = "Added" if key == "added" else "Removed"
                if rating:
                    print_text += " rating"
                click.secho(f"{print_text}:", bold=True, fg="green")
                if d[key]["movies"]:
                    click.echo(f"Movies: {d[key]['movies']}")
                if d[key]["episodes"]:
                    click.echo(f"Episodes: {d[key]['episodes']}")
        else:
            return False

        not_found_lines = []
        for k, v in d["not_found"].items():
            # return false so whole error gets printed
            if not isinstance(v, list):
                return False
            for item in v:
                not_found_lines.append(f"{k}: {repr(item)}")

        if not_found_lines:
            click.secho("Not found:", bold=True, fg="red", err=True)
            for line in not_found_lines:
                click.echo(line)

        click.echo()
        return True
    except Exception:
        # if failed to access any of the keys, skip nice print
        return False


def _print_response(d: Any, rating: bool = False) -> None:
    if _print_response_pretty(d, rating=rating):
        return
    if isinstance(d, dict):
        click.echo(json.dumps(d, indent=2), err=True)
    else:
        click.echo(d, err=True)


def _parse_url_to_input(url: str) -> Input:
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    if parts.netloc != "trakt.tv":
        click.secho(
            f"Warning; Invalid URL netloc: {parts.netloc}, expected trakt.tv",
            fg="yellow",
            err=True,
        )

    prts = [u.strip() for u in parts.path.split("/") if u.strip()]

    match prts:
        case ["movies", id, *_]:
            return MovieId(id)
        case ["shows", id, "seasons", season, "episodes", episode, *_]:
            return EpisodeId(id, int(season), int(episode))
        case ["shows", id, *_]:
            return TVShowId(id)
        case _:
            raise ValueError(f"Invalid URL parts: {prts}")


TraktType = Union[Movie, TVEpisode, TVShow]


def _mark_watched(
    input: Input,
    *,
    watched_at: Union[datetime, None, Literal["released"]] = None,
    rating: Optional[int] = None,
) -> TraktType:
    if isinstance(input, MovieId):
        mv = input.trakt()
        _print_response(mv.mark_as_seen(watched_at=watched_at))
        if rating is not None or click.confirm("Set rating?", default=True):
            if not rating:
                rating = click.prompt("Rating", type=int)
            assert isinstance(rating, int)
            _print_response(mv.rate(rating), rating=True)
        return mv
    elif isinstance(input, EpisodeId):
        ep = input.trakt()
        _print_response(ep.mark_as_seen(watched_at=watched_at))
        return ep
    elif isinstance(input, TVShowId):
        # prompt user if they want to watch an entire show or just an episode
        tv = input.trakt()
        if click.confirm("Really mark entire show as watched?", default=False):
            _print_response(tv.mark_as_seen(watched_at=watched_at))
        return tv
    else:
        raise ValueError(f"Invalid input type: {type(input)}")


def _parse_datetime(
    ctx: click.Context, param: click.Argument, value: Optional[str]
) -> Union[datetime, None, Literal["released"]]:
    import dateparser
    import warnings

    # remove pytz warning from dateparser module
    warnings.filterwarnings("ignore", "The localize method is no longer necessary")

    if value is None:
        return None

    ds = value.strip()
    if ds == "released":
        return "released"
    dt = dateparser.parse(ds)
    if dt is None:
        raise click.BadParameter(f"Could not parse '{ds}' into a date")
    else:
        ts = dt.timestamp()
        local_dt = datetime.fromtimestamp(ts)
        click.echo(f"Date: {local_dt}", err=True)
        return datetime.fromtimestamp(ts, tz=timezone.utc)


def _display_search_entry(entry: Any, *, print_urls: bool = False) -> str:
    buf: str = ""
    if isinstance(entry, Movie):
        buf += f"Movie:\t{entry.title} ({entry.year})"
        if print_urls and entry.ids.get("ids") and entry.ids["ids"].get("slug"):
            buf += f" | https://trakt.tv/movies/{entry.ids['ids']['slug']}"
        elif print_urls and entry.ext:
            buf += f" | https://trakt.tv/{entry.ext}"
    elif isinstance(entry, TVEpisode):
        buf += f"Episode:\t{entry.show} S{entry.season}E{entry.episode} - {entry.title}"
        if print_urls and entry.ext:
            buf += f" | https://trakt.tv/{entry.ext}"
    elif isinstance(entry, TVShow):
        buf += f"Show:\t{entry.title} ({entry.year})"
        if print_urls and entry.ids.get("ids") and entry.ids["ids"].get("slug"):
            buf += f" | https://trakt.tv/shows/{entry.ids['ids']['slug']}"
        elif print_urls and entry.ext:
            buf += f" | https://trakt.tv/{entry.ext}"
    elif isinstance(entry, Person):
        buf += f"Person:\t{entry.name}"
        if print_urls and entry.ids.get("ids") and entry.ids["ids"].get("slug"):
            buf += f" | https://trakt.tv/people/{entry.ids['ids']['slug']}"
        elif print_urls and entry.ext:
            buf += f" | https://trakt.tv/{entry.ext}"
    else:
        raise ValueError(f"Invalid entry type: {type(entry)}")

    return buf


def _handle_pick_result(
    user_input: str,
) -> Union[int, Literal["u"], None]:
    if user_input.strip() in {"n", "q"}:
        raise click.Abort()
    if user_input.strip() == "u":
        return "u"
    try:
        choice = int(user_input)
        return choice
    except ValueError:
        click.secho(f"Could not parse '{user_input}' into a number", fg="red", err=True)
        return None


allowed = ["M", "S", "I", "E", "A", "U"]

T = TypeVar("T")


def _pick_item(
    show_options: Callable[[bool, List[T]], None],
    /,
    *,
    prompt_prefix: str,
    items: List[T],
    show_urls_default: bool = False,
) -> T:
    choice: Optional[int] = None
    show_urls = show_urls_default
    while choice is None:
        show_options(show_urls, items)
        choice = click.prompt(
            f"{prompt_prefix}, enter 1-{len(items)}, q to quit, u to {'hide' if show_urls else 'show'} URLs",
            default="1",
            value_proc=_handle_pick_result,
        )
        if choice is None:
            continue
        if choice == "u":
            show_urls = not show_urls
            choice = None
            continue
        assert isinstance(
            choice, int
        ), f"Invalid choice type: {choice} {type(choice)}, should be int"
        if choice < 1 or choice > len(items):
            click.secho(f"Invalid choice, must be 1-{len(items)}", fg="red", err=True)
            choice = None

    return items[choice - 1]


def _search_trakt() -> Input:
    # prompt user to ask if they want to search for a
    # particular type of media, else just search for all
    # types
    click.echo(
        "[M]ovie\n[S]how\n[E]pisode name\nEp[I]sode - Show w/ Season/Episode num\n[U]rl\n[A]ll\nWhat type of media do you want to search for? ",
        nl=False,
    )
    pressed = click.getchar().upper()
    click.echo()
    if pressed.strip() == "":
        click.secho("No input", fg="red")
    elif pressed not in allowed:
        click.secho(
            f"'{pressed}', should be one of ({', '.join(allowed)})",
            fg="red",
        )
    elif pressed == "U":
        urlp = click.prompt("Url", type=str)
        return _parse_url_to_input(urlp)
    # 'movie', 'show', 'episode', or 'person'
    pressed = pressed if pressed in allowed else "A"
    media_type: Optional[str] = {
        "M": "movie",
        "S": "show",
        "I": "show",
        "E": "episode",
        "A": None,
    }.get(pressed)

    from trakt.sync import search  # type: ignore[import]

    search_term = click.prompt(f"Search for {media_type or 'all'}", type=str)
    results = search(search_term, search_type=media_type)  # type: ignore[arg-type]

    if not results:
        raise click.ClickException("No results found")

    def _display_items(show_urls: bool, items: List[TraktType]) -> None:
        click.echo("Results:")
        for i, result in enumerate(items, 1):
            click.echo(f"{i}: {_display_search_entry(result, print_urls=show_urls)}")

    result = _pick_item(_display_items, prompt_prefix="Pick result", items=results)

    result._get()
    inp = _parse_url_to_input(f"https://trakt.tv/{result.ext}")
    if pressed == "I":
        season = click.prompt("Season", type=int)
        episode = click.prompt("Episode", type=int)
        inp = EpisodeId(inp.id, season, episode)
    return inp


def _handle_input(
    ctx: click.Context, param: click.Argument, url: Optional[str]
) -> Input:
    if url is not None:
        return _parse_url_to_input(url)
    else:
        return _search_trakt()


LetterboxdChoice = Literal["prompt", "open", "none"]


def _open_url(url: str) -> None:
    if URL_OPENER := os.environ.get("URL_OPENER"):
        import subprocess
        import shutil

        path = shutil.which(URL_OPENER)
        if path is not None:
            try:
                subprocess.Popen([path, url])
                return
            except Exception as e:
                click.echo(f"Failed to open URL with {URL_OPENER=}: {e}", err=True)

    # fallback if no URL_OPENER is set
    from webbrowser import open_new_tab

    open_new_tab(url)


def _open_letterboxd(media: TraktType, policy: LetterboxdChoice) -> bool:
    # dont try to open for people/episodes
    # entire TV shows are sometimes on letterboxd if they dont have multiple
    # seasons, and movies obviously are on lb
    if not isinstance(media, (Movie, TVShow)):
        return False

    if media.ids.get("ids") and media.ids["ids"].get("tmdb"):
        url = f"https://letterboxd.com/tmdb/{media.ids['ids']['tmdb']}/"
        match policy:
            case "prompt":
                if click.confirm(f"Open {url} in browser?", default=True):
                    _open_url(url)
                    return True
            case "open":
                _open_url(url)
                return True
            case "none":
                return False
            case _:
                assert_never(policy)
        return False
    else:
        click.secho("Cannot determine Letterboxd URL for entry", fg="red", err=True)
        return False


@main.command(short_help="mark movie/episode as watched")
@click.option(
    "--url",
    "inp",
    help="URL to watch",
    metavar="URL",
    required=False,
    default=None,
    type=click.UNPROCESSED,
    callback=_handle_input,
)
@click.option(
    "-a",
    "--at",
    metavar="DATE",
    help="Watched at time (date like string, or 'released')",
    callback=_parse_datetime,
    default=None,
)
@click.option(
    "-r",
    "--rating",
    help="Rating",
    type=click.IntRange(min=1, max=10),
    default=None,
)
@click.option(
    "-l",
    "--letterboxd",
    "letterboxd",
    help="open corresponding letterboxd.com entry in your browser",
    type=click.Choice(list(get_args(LetterboxdChoice)), case_sensitive=False),
    default="none",
)
def watch(
    inp: Input,
    at: Union[datetime, Literal["released"], None],
    rating: Optional[int],
    letterboxd: LetterboxdChoice,
) -> None:
    """
    Mark an entry on trakt.tv as watched
    """
    media = _mark_watched(inp, watched_at=at, rating=rating)
    _open_letterboxd(media, policy=letterboxd)
    _print_recent_history(_recent_history_entries(limit=10))


from traktexport.dal import _parse_history, HistoryEntry

HistoryType = Literal["movies", "episodes"]


def _recent_history_entries(
    *, limit: int = 10, page: int = 1, history_type: Optional[HistoryType] = None
) -> Iterator[HistoryEntry]:
    from traktexport.export import _trakt_request

    username = USERNAME
    assert username is not None

    url_parts = ["users", username, "history"]
    if history_type is not None:
        url_parts.append(history_type)

    data = _trakt_request(
        f"{'/'.join(url_parts)}?page={page}&limit={limit}", logger=None, sleep_time=0
    )

    yield from _parse_history(data)


def _display_history_entry(
    entry: HistoryEntry, include_id: bool = False, print_urls: bool = False
) -> str:
    from traktexport.dal import Movie, Episode

    watched_at = entry.watched_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
    buf: str
    if isinstance(entry.media_data, Movie):
        buf = f"{watched_at} {entry.media_data.title}"
        if print_urls and entry.media_data.ids.trakt_slug:
            buf += f" | https://trakt.tv/movies/{entry.media_data.ids.trakt_slug}"
    elif isinstance(entry.media_data, Episode):
        ep = entry.media_data
        assert isinstance(ep, Episode)
        buf = f"{watched_at} {ep.show.title} S{ep.season}E{ep.episode} - {ep.title}"
        if print_urls and ep.show.ids.trakt_slug:
            buf += f" | https://trakt.tv/shows/{ep.show.ids.trakt_slug}/seasons/{ep.season}/episodes/{ep.episode}"
    else:
        raise ValueError(f"Invalid media_type: {entry.media_type}")

    if include_id:
        buf += f" ({entry.history_id})"
    return buf


def _print_recent_history(
    history: Iterable[HistoryEntry], include_id: bool = False, print_urls: bool = False
) -> None:
    history = list(history)  # consume so the request happens
    click.secho("Recent history:", bold=True)
    for i, entry in enumerate(history, 1):
        click.echo(
            f"{i}: {_display_history_entry(entry, include_id=include_id, print_urls=print_urls)}"
        )


@main.command(short_help="remove recent watched item")
@click.option("-i/-a", "--interactive/--non-interactive", default=True, is_flag=True)
@click.option("--yes", "-y", is_flag=True, default=False, help="Skip confirmation")
@click.option("-u", "--urls", is_flag=True, default=False, help="print URLs for items")
@click.argument("limit", type=int, default=10)
def unwatch(interactive: bool, yes: bool, limit: int, urls: bool) -> None:
    """
    Remove the last watched item from your history
    """
    from traktexport.export import _trakt_request

    data = list(_recent_history_entries(limit=limit))
    picked: HistoryEntry = data[0]
    print_urls = False
    if interactive:

        def _display_items(show_urls: bool, items: List[HistoryEntry]) -> None:
            click.echo("Recent history:")
            for i, entry in enumerate(items, 1):
                click.echo(
                    f"{i}: {_display_history_entry(entry, include_id=True, print_urls=show_urls)}"
                )

        picked = _pick_item(
            _display_items,
            prompt_prefix="Pick item to remove",
            items=data,
            show_urls_default=urls,
        )

    click.echo(
        f"Removing {_display_history_entry(picked, include_id=True, print_urls=print_urls)}...",
        err=True,
    )

    last_history_id = picked.history_id
    if not yes:
        click.confirm("Remove from history?", abort=True, default=True)

    click.echo(f"Removing {last_history_id}...", err=True)

    resp = _trakt_request(
        "sync/history/remove",
        method="post",
        data={"movies": [], "episodes": [], "ids": [last_history_id]},
        logger=logger,
        sleep_time=0,
    )

    _print_response(resp)
    _print_recent_history(_recent_history_entries(limit=limit), include_id=True)


@main.command(short_help="show recent history")
@click.option(
    "-t",
    "--type",
    "history_type",
    help="type of items to print",
    type=click.Choice(list(get_args(HistoryType)), case_sensitive=False),
)
@click.option("-u", "--urls", is_flag=True, default=False, help="print URLs for items")
@click.argument("limit", type=int, default=10)
def recent(limit: int, urls: bool, history_type: Optional[HistoryType]) -> None:
    """
    Show recent history
    """
    _print_recent_history(
        _recent_history_entries(limit=limit, history_type=history_type), print_urls=urls
    )


@main.command(short_help="mark next episode in progress")
@click.option("-u", "--urls", is_flag=True, default=False, help="print URLs for items")
@click.option("-s", "--specials", is_flag=True, default=False, help="include specials")
@click.option(
    "-a",
    "--at",
    metavar="DATE",
    help="Watched at time (date like string, or 'released')",
    callback=_parse_datetime,
    default=None,
)
def progress(urls: bool, specials: bool, at: datetime) -> None:
    """
    Mark next episode in progress as watched

    \b
    This shows the most recent episode of a show that you've watched,
    lets you pick one, and then and marks the next episode as watched
    """
    from traktexport.export import _trakt_request

    username = USERNAME
    assert username is not None

    data = _trakt_request(
        f"users/{username}/history/episodes?limit=100",
        logger=None,
        sleep_time=0,
    )

    if not data:
        click.secho("Didn't find any progress", fg="red", err=True)
        return

    from traktexport.dal import Episode, Show

    prog: dict[int, HistoryEntry] = {}

    for entry in _parse_history(data):
        if entry.action != "watch":
            continue
        if entry.media_type != "episode":
            continue
        assert isinstance(
            entry.media_data, Episode
        ), f"Invalid media_data: {entry.media_data}"
        assert isinstance(
            entry.media_data.show, Show
        ), f"Invalid show: {entry.media_data.show}"

        if entry.media_data.show.ids.trakt_id not in prog:
            prog[entry.media_data.show.ids.trakt_id] = entry
        else:
            # if this is newer than the last entry, replace it
            if entry.watched_at > prog[entry.media_data.show.ids.trakt_id].watched_at:
                prog[entry.media_data.show.ids.trakt_id] = entry

    # sort by most recently watched_at
    prog = dict(sorted(prog.items(), key=lambda x: x[1].watched_at, reverse=True))

    def _display_items(show_urls: bool, items: List[HistoryEntry]) -> None:
        click.echo("Progress:")
        for i, entry in enumerate(items, 1):
            click.echo(
                f"{i}: {_display_history_entry(entry, include_id=True, print_urls=show_urls)}"
            )

    picked = _pick_item(
        _display_items,
        prompt_prefix="Pick show, will mark the next episode as watched",
        items=list(prog.values()),
        show_urls_default=urls,
    )

    assert isinstance(
        picked.media_data, Episode
    ), f"Invalid media_data: {picked.media_data}"
    assert isinstance(
        picked.media_data.show, Show
    ), f"Invalid show: {picked.media_data.show}"

    # find next episode using watched progress
    next_data = _trakt_request(
        f"shows/{picked.media_data.show.ids.trakt_id}/progress/watched?hidden=true&specials={str(specials).lower()}",
        logger=None,
        sleep_time=0,
    )

    if not next_data:
        click.secho(
            f"No progress found for {picked.media_data.show.title}", fg="red", err=True
        )
        return

    # get data from next_data and prompt the user to confirm
    assert "next_episode" in next_data, f"Invalid next_data: {next_data}"
    next_ep = next_data["next_episode"]
    if next_ep is None:
        click.secho(
            f"No next episode found for {picked.media_data.show.title}",
            fg="red",
            err=True,
        )
        return
    assert isinstance(next_ep, dict), f"Invalid next_ep: {next_ep}"

    next_show_slug = (
        picked.media_data.ids.trakt_slug or picked.media_data.show.ids.trakt_slug
    )
    assert isinstance(next_show_slug, str), f"Invalid next_show_slug: {next_show_slug}"
    next_episode = next_ep.get("number")
    assert isinstance(next_episode, int), f"Invalid next_episode: {next_episode}"
    next_season = next_ep.get("season")
    assert isinstance(next_season, int), f"Invalid next_season: {next_season}"

    next_episode_title = next_ep.get("title")
    if next_episode_title is None:
        next_episode_title = "--"

    next_ep_str = f"{next_episode_title} (S{next_season}E{next_episode})"

    if not click.confirm(
        f"Mark '{next_ep_str}' from '{picked.media_data.show.title}' as watched?",
        default=True,
    ):
        return

    click.echo(f"Marking {next_ep_str} as watched...", err=True)

    ep = EpisodeId(next_show_slug, next_season, next_episode)
    _mark_watched(ep, watched_at=at)
    _print_recent_history(_recent_history_entries(limit=10))


def _rate_input(input: Input, rating: int) -> TraktType:
    if isinstance(input, MovieId):
        mv = input.trakt()
        _print_response(mv.rate(rating), rating=True)
        return mv
    elif isinstance(input, EpisodeId):
        ep = input.trakt()
        _print_response(ep.rate(rating), rating=True)
        return ep
    elif isinstance(input, TVShowId):
        tv = input.trakt()
        _print_response(tv.rate(rating), rating=True)
        return tv
    else:
        raise ValueError(f"Invalid input type: {type(input)}")


@main.command(short_help="rate movie/tv show/episode")
@click.option(
    "--url",
    "inp",
    help="URL to rate",
    default=None,
    type=str,
    callback=_handle_input,
)
@click.option(
    "-r",
    "--rating",
    help="Rating",
    type=click.IntRange(min=1, max=10),
    required=True,
    prompt=True,
)
@click.option(
    "-l",
    "--letterboxd",
    "letterboxd",
    help="open corresponding letterboxd.com entry in your browser",
    type=click.Choice(list(get_args(LetterboxdChoice)), case_sensitive=False),
    default="none",
)
def rate(inp: Input, rating: int, letterboxd: LetterboxdChoice) -> None:
    """
    Rate an entry on trakt.tv
    """
    media = _rate_input(inp, rating)
    _open_letterboxd(media, policy=letterboxd)


@main.command(short_help="open letterboxd.com entry")
@click.option(
    "--url",
    "inp",
    help="URL to rate",
    default=None,
    type=str,
    callback=_handle_input,
)
def letterboxd(inp: Input) -> None:
    """
    Open corresponding letterboxd.com entry in your browser
    """
    if not _open_letterboxd(inp.trakt(), policy="open"):
        click.secho("Could not open Letterboxd URL", fg="red", err=True)


if __name__ == "__main__":
    main(prog_name="trakt-watch")
