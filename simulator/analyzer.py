"""
Results Analyzer
Analyzes simulation results to identify patterns and improvement opportunities
"""
import json
from pathlib import Path
from typing import List, Dict
from datetime import datetime
from collections import defaultdict


class ResultsAnalyzer:
    """Analyzes simulation results to find improvement opportunities"""
    
    def __init__(self, results_dir: str = "simulator/results"):
        self.results_dir = Path(results_dir)
    
    def load_results(self, filename: str) -> dict:
        """Load results from JSON file"""
        filepath = self.results_dir / filename
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def analyze_extraction_patterns(self, results: dict) -> dict:
        """Analyze what patterns are being missed"""
        analysis = {
            'total_messages': results['total_messages'],
            'extraction_rate': 0.0,
            'failed_patterns': [],
            'missing_symbols': [],
            'missing_actions': [],
            'incomplete_signals': []
        }
        
        extracted = results['ai_extracted_count'] + results['pattern_extracted_count']
        analysis['extraction_rate'] = (extracted / results['total_messages'] * 100) if results['total_messages'] > 0 else 0
        
        # Analyze failed extractions
        for trade in results['trades']:
            if not trade['ai_extracted'] and not trade['pattern_extracted']:
                # Categorize the failure
                msg = trade['original_message'].upper()
                
                # Check for trading keywords
                has_buy = any(kw in msg for kw in ['BUY', 'LONG', '🟢'])
                has_sell = any(kw in msg for kw in ['SELL', 'SHORT', '🔴'])
                has_close = any(kw in msg for kw in ['CLOSE', 'EXIT'])
                
                if has_buy or has_sell or has_close:
                    # Has action keywords but failed - likely missing symbol or prices
                    if not any(sym in msg for sym in ['GOLD', 'XAU', 'EUR', 'GBP', 'US30', 'NAS']):
                        analysis['missing_symbols'].append({
                            'message': trade['original_message'][:100],
                            'message_id': trade['message_id']
                        })
                    else:
                        analysis['incomplete_signals'].append({
                            'message': trade['original_message'][:100],
                            'message_id': trade['message_id'],
                            'error': trade.get('extraction_error', 'Unknown')
                        })
                else:
                    # No clear action keywords
                    analysis['missing_actions'].append({
                        'message': trade['original_message'][:100],
                        'message_id': trade['message_id']
                    })
        
        return analysis
    
    def analyze_symbol_accuracy(self, results: dict) -> dict:
        """Analyze symbol extraction accuracy"""
        symbol_stats = defaultdict(lambda: {'total': 0, 'ai': 0, 'pattern': 0})
        
        for trade in results['trades']:
            if trade['ai_extracted']:
                symbol = trade.get('ai_symbol')
                if symbol:
                    symbol_stats[symbol]['total'] += 1
                    symbol_stats[symbol]['ai'] += 1
            elif trade['pattern_extracted']:
                symbol = trade.get('pattern_symbol')
                if symbol:
                    symbol_stats[symbol]['total'] += 1
                    symbol_stats[symbol]['pattern'] += 1
        
        return dict(symbol_stats)
    
    def analyze_action_accuracy(self, results: dict) -> dict:
        """Analyze action extraction accuracy"""
        action_stats = defaultdict(lambda: {'total': 0, 'ai': 0, 'pattern': 0})
        
        for trade in results['trades']:
            if trade['ai_extracted']:
                action = trade.get('ai_action')
                if action:
                    action_stats[action]['total'] += 1
                    action_stats[action]['ai'] += 1
            elif trade['pattern_extracted']:
                action = trade.get('pattern_action')
                if action:
                    action_stats[action]['total'] += 1
                    action_stats[action]['pattern'] += 1
        
        return dict(action_stats)
    
    def find_improvement_opportunities(self, results: dict) -> dict:
        """Identify specific improvement opportunities"""
        opportunities = {
            'new_patterns_needed': [],
            'symbol_mappings_needed': [],
            'action_keywords_needed': [],
            'price_extraction_issues': []
        }
        
        # Analyze failed extractions
        for trade in results['trades']:
            if not trade['ai_extracted'] and not trade['pattern_extracted']:
                msg = trade['original_message']
                
                # Look for unrecognized patterns
                if any(kw in msg.upper() for kw in ['BUY', 'SELL', 'LONG', 'SHORT']):
                    # Has action but failed - analyze why
                    
                    # Check for unusual symbol names
                    words = msg.split()
                    for word in words:
                        if len(word) >= 3 and word.isupper() and word not in ['BUY', 'SELL', 'NOW', 'SL', 'TP']:
                            opportunities['symbol_mappings_needed'].append({
                                'potential_symbol': word,
                                'message': msg[:100]
                            })
                    
                    # Check for price patterns
                    if '@' in msg or 'ENTRY' in msg.upper():
                        opportunities['price_extraction_issues'].append({
                            'message': msg[:100],
                            'issue': 'Has entry indicator but failed extraction'
                        })
        
        # Deduplicate
        opportunities['symbol_mappings_needed'] = self._deduplicate_by_key(
            opportunities['symbol_mappings_needed'], 'potential_symbol'
        )
        
        return opportunities
    
    def _deduplicate_by_key(self, items: List[dict], key: str) -> List[dict]:
        """Remove duplicates based on a key"""
        seen = set()
        result = []
        for item in items:
            if item[key] not in seen:
                seen.add(item[key])
                result.append(item)
        return result
    
    def generate_report(self, results: dict) -> str:
        """Generate comprehensive analysis report"""
        report = []
        report.append("="*80)
        report.append("SIMULATION ANALYSIS REPORT")
        report.append("="*80)
        report.append(f"\nChannel: {results['channel_name']}")
        report.append(f"Period: {results['start_date']} to {results['end_date']}")
        report.append(f"Total Messages: {results['total_messages']}")
        
        # Extraction Analysis
        extraction = self.analyze_extraction_patterns(results)
        report.append(f"\n{'='*80}")
        report.append("EXTRACTION PERFORMANCE")
        report.append("="*80)
        report.append(f"Extraction Rate: {extraction['extraction_rate']:.1f}%")
        report.append(f"Failed Extractions: {len(extraction['missing_symbols']) + len(extraction['missing_actions']) + len(extraction['incomplete_signals'])}")
        
        if extraction['missing_symbols']:
            report.append(f"\nMissing Symbols ({len(extraction['missing_symbols'])} messages):")
            for item in extraction['missing_symbols'][:5]:
                report.append(f"  - {item['message']}")
        
        if extraction['missing_actions']:
            report.append(f"\nMissing Actions ({len(extraction['missing_actions'])} messages):")
            for item in extraction['missing_actions'][:5]:
                report.append(f"  - {item['message']}")
        
        # Symbol Accuracy
        symbol_stats = self.analyze_symbol_accuracy(results)
        report.append(f"\n{'='*80}")
        report.append("SYMBOL EXTRACTION")
        report.append("="*80)
        for symbol, stats in sorted(symbol_stats.items(), key=lambda x: x[1]['total'], reverse=True)[:10]:
            report.append(f"{symbol}: {stats['total']} (AI: {stats['ai']}, Pattern: {stats['pattern']})")
        
        # Action Accuracy
        action_stats = self.analyze_action_accuracy(results)
        report.append(f"\n{'='*80}")
        report.append("ACTION EXTRACTION")
        report.append("="*80)
        for action, stats in sorted(action_stats.items(), key=lambda x: x[1]['total'], reverse=True):
            report.append(f"{action}: {stats['total']} (AI: {stats['ai']}, Pattern: {stats['pattern']})")
        
        # Improvement Opportunities
        opportunities = self.find_improvement_opportunities(results)
        report.append(f"\n{'='*80}")
        report.append("IMPROVEMENT OPPORTUNITIES")
        report.append("="*80)
        
        if opportunities['symbol_mappings_needed']:
            report.append(f"\nNew Symbol Mappings Needed ({len(opportunities['symbol_mappings_needed'])}):")
            for item in opportunities['symbol_mappings_needed'][:10]:
                report.append(f"  - {item['potential_symbol']}: {item['message'][:60]}...")
        
        if opportunities['price_extraction_issues']:
            report.append(f"\nPrice Extraction Issues ({len(opportunities['price_extraction_issues'])}):")
            for item in opportunities['price_extraction_issues'][:5]:
                report.append(f"  - {item['message'][:60]}...")
        
        # Error Analysis
        if results.get('common_errors'):
            report.append(f"\n{'='*80}")
            report.append("COMMON ERRORS")
            report.append("="*80)
            for error, count in sorted(results['common_errors'].items(), key=lambda x: x[1], reverse=True)[:10]:
                report.append(f"[{count}x] {error[:70]}")
        
        report.append(f"\n{'='*80}")
        report.append("RECOMMENDATIONS")
        report.append("="*80)
        
        # Generate recommendations
        if extraction['extraction_rate'] < 70:
            report.append("\n⚠️  LOW EXTRACTION RATE (<70%)")
            report.append("   - Review failed messages to identify missing patterns")
            report.append("   - Add new symbol mappings for unrecognized symbols")
            report.append("   - Enhance action keyword detection")
        
        if len(opportunities['symbol_mappings_needed']) > 5:
            report.append(f"\n⚠️  MANY UNRECOGNIZED SYMBOLS ({len(opportunities['symbol_mappings_needed'])})")
            report.append("   - Add symbol mappings to integrated_processor.py")
            report.append("   - Update symbol normalization in utils/helpers.py")
        
        if results['ai_extracted_count'] == 0 and results.get('ai', {}).get('openai_api_key'):
            report.append("\n⚠️  AI NOT WORKING")
            report.append("   - Check API key and quota")
            report.append("   - Verify OpenAI/DeepSeek configuration")
        
        report.append("\n" + "="*80)
        
        return "\n".join(report)
    
    def save_report(self, results: dict, output_file: str = None):
        """Save analysis report to file"""
        report = self.generate_report(results)
        
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"{results['channel_name']}_analysis_{timestamp}.txt"
        
        output_path = self.results_dir / output_file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"Analysis report saved to: {output_path}")
        return output_path


def main():
    """Analyze latest simulation results"""
    import sys
    
    analyzer = ResultsAnalyzer()
    
    # Get latest results file
    results_files = sorted(analyzer.results_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    
    if not results_files:
        print("No simulation results found. Run a simulation first.")
        return
    
    if len(sys.argv) > 1:
        # Use specified file
        results_file = sys.argv[1]
    else:
        # Use latest file
        results_file = results_files[0].name
        print(f"Analyzing latest results: {results_file}\n")
    
    # Load and analyze
    results = analyzer.load_results(results_file)
    
    # Print report
    report = analyzer.generate_report(results)
    print(report)
    
    # Save report
    analyzer.save_report(results)


if __name__ == "__main__":
    main()
