#!/usr/bin/perl
# Matija Nalis <mnalis-git@voyager.hr> GPLv3+, started 2015-04-17
#
# detektira zalihe krvi u HZTMu, kako bi RSSom mogao dojaviti korisnicima kada neke krvne grupe nedostaje.
#
# in Debian requisite modules are installed with: "apt-get install libhtml-treebuilder-xpath-perl libxml-feed-perl libcgi-pm-perl"
#
# FIXME - RSS/Atom - only display last 10 or changes
# FIXME - na mnalis.com/hztm stavi html formu da biras RSS/Atom i koju krvnu grupu.
# FIXME - also handle "too much blood for this group" condition later


use strict;
use warnings;
use Carp qw(verbose);
use autodie;
use feature qw(say);
use CGI;
use CGI::Carp qw(fatalsToBrowser);
use Encode qw(decode);
use LWP::UserAgent;
use Text::CSV qw(csv);
use XML::Feed;
use IO::Handle;
use Fcntl ':flock';
use POSIX qw(strftime);

################################
# user configuration variables #
################################
my $EXPIRES_SECONDS = 60*60*12;		# indicate RSS should be cached for this many seconds (to try to lower load on server)
my $HISTORY_DATA = 'krvne_grupe.history.txt';
my $UPDATE_SECONDS = 60*60*24*1;	# force update if not changed for this many seconds (safety fallback in case script is never called from cron with update=1). you may want increase to a week, or comment out if this feature is not wanted.


###################################
# no user serviceable parts below #
###################################
my $q = new CGI;
my $VERSION = '2022-06-14';	# change script version here.
my $HZTM_URL = 'https://hztm.hr/zalihe_krvi/';
my $HZTM_DATA_URL = 'https://hztm.hr/doze/blood_data.html';
my $HISTORY_TMP = $HISTORY_DATA . '.tmp';
my $force_update = 0;
my @history = ();
my %zadnja = ();
my $old_datafile = '';

#####################
#### CGI helpers ####
#####################

# validate params
sub _validate($$$)
{
  my ($param, $regex, $ok_null) = @_;
  my $value = $q->param($param);
  if (!defined($value)) {
    return undef if $ok_null;
    die "no param $param specified";
  }
  if ($value =~ /^(${regex})$/i) {
     $value = $1; 
     return $value;
  } 
  die "invalid value for param $param = $value";
}

sub validate($$)
{
  my ($param, $regex) = @_;
  return _validate ($param, $regex, 0);
}

sub validate_oknull($$)
{
  my ($param, $regex) = @_;
  return _validate ($param, $regex, 1);
}


############################
#### here goes the main ####
############################

my $xml_feed = 'Atom';
my $mime = 'application/atom+xml';

my $feed_type = validate_oknull('feed', 'Atom|RSS2?') || 'Atom';
if ($feed_type =~ /rss/i) {		# if we want to use older RSS2 instead of Atom1 XML feed
    $xml_feed = 'RSS';
    $mime = 'application/rss+xml';
}


my $krv_grupa = validate('grupa', '(0|A|B|AB)(minus|plus)');
$krv_grupa =~ s/minus/=/;
$krv_grupa =~ s/plus/+/;
$krv_grupa = uc($krv_grupa);

open my $IN, '<', $HISTORY_DATA or die "can't read $HISTORY_DATA: $!";
flock($IN, LOCK_EX) or die "Could not lock $HISTORY_DATA: $!";

my $datafile_mtime = (stat($HISTORY_DATA))[9];
my $age = time() - $datafile_mtime;
#say "$HISTORY_DATA mtime=$datafile_mtime, age=$age";
if (defined ($UPDATE_SECONDS) and  ($age > $UPDATE_SECONDS)) {
    $force_update = 1; 
}

my $p_update = validate_oknull('update', '0|1|on') || 0;
if ($p_update or $force_update) {
    parse_html_and_update_history();		# update if explicitely requested, of if due
} else {
    read_datafile();
}

generate_and_display_rss();

exit 0;



################################################################
# generate and display RSS/Atom feed for requested blood group #
################################################################
sub generate_and_display_rss
{
        print $q->header( -type => $mime, 
                          -charset=> 'utf-8',
                          -cache_control => "max-age=${EXPIRES_SECONDS}, public", 
                          -expires=> "+${EXPIRES_SECONDS}s",  
              );
              
        my $feed = XML::Feed->new($xml_feed);
        my $TAG_BASE = 'tag:mnalis.com,2015-04-17:/hztm';	# DO NOT EDIT EVER!!
        my $feed_id = "/HZTM-krv-unoff/$krv_grupa"; 
        my $url = $q->url( -query => 1, -full => 1, -rewrite => 1);
        $feed->self_link($url);
        $feed->title( "Nedostatak krvne grupe $krv_grupa u HZTM" );
        $feed->id( "$TAG_BASE/$feed_id" );
        $feed->description( "Niske zalihe krvi grupe $krv_grupa (za dobrovoljne darivatelje krvi Hrvatskog zavoda za transfuzijsku medicinu)" );
        $feed->language('hr');
        $feed->copyright('Informacije su preuzete iz vanjskih izvora te ne odgovaramo za njihovu točnost');
        $feed->author('mnalis-hztm@voyager.hr ( http://mnalis.com/hztm/ )');
        $feed->generator("hztm_rss.cgi $VERSION using XML::Feed " . $XML::Feed::VERSION);
        $feed->link($url);

        my $last_timestamp = 0;
        foreach my $event (@history) {
            next if $event->{grupa} ne $krv_grupa;		# skip over blood groups we don't want to display in this run
            my $entry = XML::Feed::Entry->new($xml_feed);
            $entry->id( "$TAG_BASE/" . $event->{timestamp} . $feed_id );              # see http://taguri.org (RFC 4151), and http://web.archive.org/web/20110514113830/http://diveintomark.org/archives/2004/05/28/howto-atom-id
            $entry->link( $HZTM_URL );
            my $datum = strftime("%d.%m.%Y", localtime($event->{timestamp}));

            if ($event->{nedostaje}) {
                $entry->title( "$datum Nedostaje $event->{grupa} krvne grupe" );
                $entry->content( "Sa datumom $datum nedostaje krvne grupe $event->{grupa} (zalihe su samo $event->{posto}%). \nMolimo da se odazovete dobrovoljnom davanju krvi.\n\nHvala unaprijed!" );
            } else {
                $entry->title( "$datum Ponovno ima dovoljno krvne grupe $event->{grupa}" );
                $entry->content( "Sa datumom $datum ponovo ima dovoljno ($event->{posto}%) krvne grupe $event->{grupa}" );
            }
            
            $entry->issued(   DateTime->from_epoch(epoch => $event->{timestamp}) );
            $entry->modified( DateTime->from_epoch(epoch => $event->{timestamp}) );
            
            $last_timestamp = $event->{timestamp} if $event->{timestamp} > $last_timestamp;	# increment last feed update timestamp if needed.
            
            $feed->add_entry($entry);
        }
        $feed->modified (DateTime->from_epoch(epoch => $last_timestamp));

        say $feed->as_xml;
}


# reads whole datafile in @history (and $old_datafile), and updated %zadnja
sub read_datafile
{
        @history = ();
        %zadnja = ();
        $old_datafile = '';
        seek $IN, 0, 0;		# position to beginning of the file

        while (<$IN>) {
            chomp;
            my ($h_timestamp, $h_grupa, $h_nedostaje, $h_posto) = split /\t/; $h_nedostaje = 0 if ! $h_nedostaje;
            #say "[$#history] $h_timestamp, $h_grupa, $h_nedostaje, $h_posto";
            push @history, { timestamp => $h_timestamp, grupa => $h_grupa, nedostaje => $h_nedostaje, posto => $h_posto };
            $old_datafile .= "$h_timestamp\t$h_grupa\t$h_nedostaje\t$h_posto\n";
            $zadnja{$h_grupa} = { timestamp => $h_timestamp, grupa => $h_grupa, nedostaje => $h_nedostaje, posto => $h_posto } if !defined $zadnja{$h_grupa};
        }
}

# fetches and returns data from specified URL, or dies with error
sub fetch_url($)
{
        my ($url) = @_;
        
        my $ua = LWP::UserAgent->new;
        $ua->agent("hztm_rss.cgi/$VERSION ");

        # Create a request
        my $req = HTTP::Request->new(GET => $url);

        # Pass request to the user agent and get a response back
        my $res = $ua->request($req);

        # Check the outcome of the response
        if ($res->is_success) {
            return $res->content;
        }
        else {
            die "failed fetching $url: " . $res->status_line;
        }
}

###########################################################
# parse HTZM HTML and update history datafiles if changed #
###########################################################
sub parse_html_and_update_history
{
        ########################
        #### parse the HTML ####
        ########################
        
 
# example html:       
#const groups = {
#    'A+': {min: 0, max: 535, full: 510, empty: 0, el: document.getElementById('aplus')},
#    'A-': {min: 0, max: 118, full: 110, empty: 0, el: document.getElementById('aminus')},
#    'B+': {min: 0, max: 284, full: 255, empty: 0, el: document.getElementById('bplus')},
#    'B-': {min: 0, max: 54, full: 65, empty: 0, el: document.getElementById('bminus')},
#    'O+': {min: 0, max: 525, full: 510, empty: 0, el: document.getElementById('zeroplus')},
#    'O-': {min: 0, max: 111, full: 110, empty: 0, el: document.getElementById('zerominus')},
#    'AB+': {min: 0, max: 127, full: 125, empty: 0, el: document.getElementById('abplus')},
#    'AB-': {min: 0, max: 25, full: 30, empty: 0, el: document.getElementById('abminus')}
#}


        #my $html = fetch_url($HZTM_URL); #FIXME
        my $html = fetch_url('file:./blood_data_index.html');
        #say $html;
        # NB: unfortunately, JSON:PP even with all allow_* fails parsing at document.getElementById, so we have to this manually :(
        if ($html =~ /const\s+groups\s*=\s*\{\s*(.*?)^\s*\}\s*$/gms) {
          my @consts = split /^/, $1;
          foreach my $c (@consts) {
            #say "c=$c";
            if ($c =~ m/
                    '([ABO]+[+-])'\s*:\s*{
                    min\s*:\s*(\d+)\s*,\s*
                    max\s*:\s*(\d+)\s*,\s*
                    full\s*:\s*(\d+)\s*,\s*
                    empty\s*:\s*(\d+)\s*,\s*
                /x) {
              say "g=$1, min=$2, max=$3, full=$4, empty=$5";
            } else {
              die "can't parse const: $c";
            }
          }
        } else {
          die "FAILED: can't parse HTML JS"
        }
        
        #my $data = fetch_url($HZTM_DATA_URL); #FIXME
        
        die "fixme /mn/";


        my $HZTM_FILE = 'blood_data.html'; my $tree= HTML::TreeBuilder::XPath->new_from_file($HZTM_FILE);	# DEBUG ONLY
        #my $tree= HTML::TreeBuilder::XPath->new_from_url($HZTM_DATA_URL);

        my @sve=$tree->findnodes( '/html/body//div[@id="supplies"]/div[contains(concat(" ", normalize-space(@class), " "),"measure")]' );

        my %current = ();
        my $c_timestamp = time;

        for my $jedna (@sve) {
            my $c_posto = int ($jedna->findnodes( 'div[@class="outer"]/div[@class="inner"]' )->[0]->attr('data-percent'));
            my $ime = $jedna->findnodes( 'div[contains(concat(" ", normalize-space(@class), " "),"name")]' )->[0];
            my $c_grupa = $ime->content->[0];
            my $attr = $ime->attr('class');
            my $c_nedostaje = ($attr =~ /\bbig\b/) || 0;
            #say "grupa=$grupa, attr=$attr, nedostaje=$nedostaje, posto=$posto";
            #say '' . ($c_nedostaje?'Nedostaje':'Ima dovoljno') . " krvne grupe $c_grupa ($c_posto %)";
            $current{$c_grupa} = { timestamp => $c_timestamp, grupa => $c_grupa, nedostaje => $c_nedostaje, posto => $c_posto };
        }

        ##############################
        #### update history files ####
        ##############################
        my $changed = $force_update;	# force datafile rewrite if not changed for too long

        read_datafile();	# fills @history, %zadnja, $old_datafile
        my $prepend_datafile = '';
        foreach my $k (keys %current) {
            #say "current key $k($current{$k}{grupa}) => ($current{$k}{nedostaje}) $current{$k}{posto}%";
            if (!%zadnja or ($current{$k}{nedostaje} ne $zadnja{$k}{nedostaje})) {
                $prepend_datafile .= "$current{$k}{timestamp}\t$current{$k}{grupa}\t$current{$k}{nedostaje}\t$current{$k}{posto}\n";
                unshift @history, { timestamp => $current{$k}{timestamp}, grupa => $current{$k}{grupa}, nedostaje => $current{$k}{nedostaje}, posto => $current{$k}{posto} };	# prepend newly parsed HTML to @history
                $changed = 1;
            }
        }


        if ($changed) {		# only update if actually changed
            $datafile_mtime = time;	# indicate it just changed
            # note: we'd be more efficient with just appended to main datafile, but it is not safe in event of crash. so we rewrite to temp file + rename if all is OK. And we prefer prepending instead of appending.
            open my $OUT, '>', $HISTORY_TMP or die "can't create $HISTORY_TMP: $!";
            flock($OUT, LOCK_EX) or die "Could not lock $HISTORY_TMP: $!";
            print $OUT "${prepend_datafile}${old_datafile}" or die "can't write to $HISTORY_TMP: $!";

            # hopefully this provides atomicity (but not durability [which is not important to us] as we don't fsync dir after rename) -- see http://stackoverflow.com/questions/7433057/is-rename-without-fsync-safe & http://lwn.net/Articles/457667/
            $OUT->flush or die "can't flush $HISTORY_TMP: $!";
            $OUT->sync or die "can't fsync $HISTORY_TMP: $!";
            rename $HISTORY_TMP, $HISTORY_DATA or die "can't rename $HISTORY_TMP to $HISTORY_DATA: $!";
        }
        # they will close automatically on program exit; do not release locks too soon
        #close ($OUT) or die "can't close $HISTORY_DATA: $!";
        #close ($IN);
}
