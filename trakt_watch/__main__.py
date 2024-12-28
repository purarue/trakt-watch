#!/usr/bin/env python3

import os
import json
from typing import (
    get_args,
    assert_never,
    List,
    Sequence,
    Literal,
    Optional,
    Union,
    Iterator,
    Iterable,
    Any,
)
from datetime import datetime, timezone

import click
from logzero import logger  # type: ignore[import]

from .core import (
    TVShowId,
    MovieId,
    pick_item,
    search_trakt,
    parse_url_to_input,
    EpisodeId,
    Input,
    TraktType,
)


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
    from traktexport.export import _check_config

    USERNAME = username
    _check_config()


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
                click.secho("No items changed", bold=True, fg="red")
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
        assert_never(input)


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


def _handle_input(
    ctx: click.Context, param: click.Argument, url: Optional[str]
) -> Input:
    if url is not None and url.strip():
        return parse_url_to_input(url)
    else:
        return search_trakt()


LetterboxdPolicy = Literal["prompt", "open", "print", "none"]


def _open_url(url: str) -> None:
    if URL_OPENER := os.environ.get("URL_OPENER"):
        import subprocess
        import shutil

        path = shutil.which(URL_OPENER)
        if path is not None:
            try:
                subprocess.run([path, url], check=True)
                return
            except Exception as e:
                click.echo(f"Failed to open URL with {URL_OPENER=}: {e}", err=True)

    # fallback if no URL_OPENER is set
    from webbrowser import open_new_tab

    open_new_tab(url)


def _open_letterboxd(media: TraktType, policy: LetterboxdPolicy) -> bool:
    from trakt.movies import Movie as TraktMovie  # type: ignore[import]
    from trakt.tv import TVShow as TraktTVShow  # type: ignore[import]

    # dont try to open for people/episodes
    # entire TV shows are sometimes on letterboxd if they dont have multiple
    # seasons, and movies obviously are on lb
    if not isinstance(media, (TraktMovie, TraktTVShow)):
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
            case "print":
                click.echo(url)
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
    type=click.Choice(list(get_args(LetterboxdPolicy)), case_sensitive=False),
    default="none",
)
def watch(
    inp: Input,
    at: Union[datetime, Literal["released"], None],
    rating: Optional[int],
    letterboxd: LetterboxdPolicy,
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
@click.option("-y", "--yes", is_flag=True, default=False, help="Skip confirmation")
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

        picked = pick_item(
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


def _unwrap_int(value: Any, error_msg: str) -> int:
    if isinstance(value, int):
        return value
    elif isinstance(value, str) and value.isdigit():
        return int(value)
    elif isinstance(value, float):
        return int(value)
    else:
        raise ValueError(f"Invalid value, expected int: {value}")


@main.command(short_help="mark next episode in progress")
@click.option("-u", "--urls", is_flag=True, default=False, help="print URLs for items")
@click.option("-s", "--specials", is_flag=True, default=False, help="include specials")
@click.option("-y", "--yes", is_flag=True, default=False, help="Skip confirmation")
@click.option(
    "-m",
    "--manual-next-ep",
    is_flag=True,
    default=False,
    help="manually compute the next episode using the last watched, instead of asking trakt",
)
@click.option(
    "-a",
    "--at",
    metavar="DATE",
    help="Watched at time (date like string, or 'released')",
    callback=_parse_datetime,
    default=None,
)
@click.argument("LIMIT", type=int, nargs=-1)
def progress(
    urls: bool,
    yes: bool,
    specials: bool,
    at: datetime,
    limit: Sequence[int],
    manual_next_ep: bool,
) -> None:
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

    def _display_items(show_urls: bool, items: List[HistoryEntry]) -> None:
        click.echo("Progress:")
        for i, entry in enumerate(items, 1):
            click.echo(
                f"{i}: {_display_history_entry(entry, include_id=True, print_urls=show_urls)}"
            )

    # sort by most recently watched_at
    prog = dict(sorted(prog.items(), key=lambda x: x[1].watched_at, reverse=True))

    current_eps = list(prog.values())
    if limit:
        current_eps = current_eps[: limit[0]]

    picked = pick_item(
        _display_items,
        prompt_prefix="Pick show, will mark the next episode as watched",
        items=current_eps,
        show_urls_default=urls,
    )

    assert isinstance(
        picked.media_data, Episode
    ), f"Invalid media_data: {picked.media_data}"
    assert isinstance(
        picked.media_data.show, Show
    ), f"Invalid show: {picked.media_data.show}"

    if manual_next_ep is False:
        # find next episode using watched progress
        next_data = _trakt_request(
            f"shows/{picked.media_data.show.ids.trakt_id}/progress/watched?hidden=true&specials={str(specials).lower()}",
            logger=None,
            sleep_time=0,
        )
    else:
        next_data = {"next_episode": None}

    next_season: int
    next_episode: int

    next_show_slug = (
        picked.media_data.ids.trakt_slug or picked.media_data.show.ids.trakt_slug
    )
    assert isinstance(next_show_slug, str), f"Invalid next_show_slug: {next_show_slug}"

    next_ep_data = next_data.get("next_episode")
    if manual_next_ep is True and next_ep_data is not None:
        assert isinstance(next_ep_data, dict), f"Invalid next_ep: {next_ep_data}"

        next_episode = _unwrap_int(
            next_ep_data.get("number"),
            f"Invalid next_episode {next_ep_data.get('number')}",
        )
        next_season = _unwrap_int(
            next_ep_data.get("season"),
            f"Invalid next_season {next_ep_data.get('season')}",
        )
        next_episode_title = next_ep_data.get("title") or "--"
    else:
        from trakt.tv import TVSeason  # type: ignore[import]

        next_episode_title = "--"
        # otherwise, use the last item in progress to find the next episode
        # by making a request to trakt to find the next episode manually
        #
        # this often happens when Im rewatching a show
        cur_season = picked.media_data.season
        cur_episode = picked.media_data.episode

        trakt_id = TVShowId(next_show_slug)
        trakt_obj = trakt_id.trakt()
        assert isinstance(trakt_obj.seasons, list)
        season_data: dict[int, TVSeason] = {s.season: s for s in trakt_obj.seasons}

        current_season_obj = season_data.get(cur_season)
        if current_season_obj is None:
            click.secho(
                f"Could not find the current season for {trakt_obj.title}",
                fg="red",
                err=True,
            )
            return
        # if next ep exists in current season, use that
        for ep in current_season_obj.episodes:
            if ep.number == cur_episode + 1:
                next_episode = ep.number
                next_season = ep.season
                next_episode_title = ep.title
                break
        else:
            # if we didn't find the next episode in current season
            next_season_obj = season_data.get(cur_season + 1)
            if next_season_obj is None:
                click.secho(
                    f"Could not find the next season for {trakt_obj.title}",
                    fg="red",
                    err=True,
                )
                return
            else:
                # else use the next season, if it exists
                next_season = cur_season + 1
                next_episode = 1
                next_episode_title = next_season_obj.episodes[0].title

    next_ep_str = f"{next_episode_title} (S{next_season}E{next_episode})"

    if not yes and not click.confirm(
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


def _unrate_input(input: Input) -> None:
    data = {}
    if isinstance(input, MovieId):
        mv = input.trakt()
        data["movies"] = [{"ids": mv.ids.get("ids", {})}]
        assert data["movies"][0]["ids"], f"Invalid movie ids: {data['movies']} {mv.ids}"
    elif isinstance(input, EpisodeId):
        ep = input.trakt()
        data["episodes"] = [{"ids": ep.ids.get("ids", {})}]
        assert data["episodes"][0][
            "ids"
        ], f"Invalid episode ids: {data['episodes']} {ep.ids}"
    elif isinstance(input, TVShowId):
        tv = input.trakt()
        data["shows"] = [{"ids": tv.ids.get("ids", {})}]
        assert data["shows"][0]["ids"], f"Invalid show ids: {data['shows']} {tv.ids}"
    else:
        raise ValueError(f"Invalid input type: {type(input)}")

    from traktexport.export import _trakt_request

    resp = _trakt_request(
        "sync/ratings/remove", data=data, logger=logger, method="post"
    )

    _print_response(resp, rating=True)


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
    type=click.Choice(list(get_args(LetterboxdPolicy)), case_sensitive=False),
    default="none",
)
def rate(inp: Input, rating: int, letterboxd: LetterboxdPolicy) -> None:
    """
    Rate an entry on trakt.tv
    """
    media = _rate_input(inp, rating)
    _open_letterboxd(media, policy=letterboxd)


@main.command(short_help="unrate movie/tv show/episode")
@click.option(
    "--url",
    "inp",
    help="URL to unrate",
    default=None,
    type=str,
    callback=_handle_input,
)
def unrate(inp: Input) -> None:
    """
    Unrate an entry on trakt.tv
    """
    _unrate_input(inp)


@main.command(short_help="open letterboxd.com entry")
@click.option(
    "--url",
    "inp",
    help="URL to rate",
    default=None,
    type=str,
    callback=_handle_input,
)
@click.option(
    "-a",
    "--action",
    "policy",
    help="how to open letterboxd.com entry",
    type=click.Choice(list(get_args(LetterboxdPolicy)), case_sensitive=False),
    default="open",
)
def letterboxd(inp: Input, policy: LetterboxdPolicy) -> None:
    """
    Open corresponding letterboxd.com entry in your browser
    """
    if not _open_letterboxd(inp.trakt(), policy=policy):
        click.secho("Could not open Letterboxd URL", fg="red", err=True)


if __name__ == "__main__":
    main(prog_name="trakt-watch")
